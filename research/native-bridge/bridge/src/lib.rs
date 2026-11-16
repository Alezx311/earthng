//! Experimental in-process tile worker pool for EarthNG (research; not a release API).
//!
//! loader.py loads this DLL into one isolated BeamNG test process and calls
//! `earthng_probe(marker)`. A listener on 127.0.0.1 (port and token written beside the
//! marker) takes one persistent connection from GE Lua. Each worker thread owns a LuaJIT VM
//! that runs the very Lua sources the game sent (generator.lua & co.), reads the pack's cell
//! blocks from the ZIPs on disk, and sends the tile's manifests back as compact binary parts.
//! The game frame never waits: GE Lua polls, and anything late, cancelled or failed is built
//! by the ordinary Lua path. No engine calls happen here.
//!
//! Frames: u32 length | u32 type | payload (little endian). See `protocol` constants.

use std::collections::{BinaryHeap, HashMap};
use std::fs::File;
use std::io::{BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

pub mod protocol {
    pub const VERSION: u32 = 2;
    // client -> bridge
    pub const HELLO: u32 = 1;
    pub const SOURCES: u32 = 2;
    pub const REGION: u32 = 3;
    pub const JOB: u32 = 4;
    pub const PRIORITY: u32 = 5;
    pub const CANCEL: u32 = 6;
    pub const FS_FALSE: u32 = 7;
    pub const BYE: u32 = 8;
    // bridge -> client
    pub const HELLO_OK: u32 = 101;
    pub const PART: u32 = 102;
    pub const DONE: u32 = 103;
    pub const NOTE: u32 = 104;
    // DONE status
    pub const OK: u32 = 0;
    pub const CANCELLED: u32 = 1;
    pub const FAILED: u32 = 2;
    pub const BUSY: u32 = 3;
    pub const MAX_FRAME: usize = 64 * 1024 * 1024;
}
use protocol::*;

fn u32at(b: &[u8], p: usize) -> Result<u32, String> {
    b.get(p..p + 4).map(|s| u32::from_le_bytes(s.try_into().unwrap())).ok_or_else(|| "truncated".into())
}
fn u64at(b: &[u8], p: usize) -> Result<u64, String> {
    b.get(p..p + 8).map(|s| u64::from_le_bytes(s.try_into().unwrap())).ok_or_else(|| "truncated".into())
}
fn f64at(b: &[u8], p: usize) -> Result<f64, String> {
    b.get(p..p + 8).map(|s| f64::from_le_bytes(s.try_into().unwrap())).ok_or_else(|| "truncated".into())
}

pub fn frame(kind: u32, parts: &[&[u8]]) -> Vec<u8> {
    let n: usize = 4 + parts.iter().map(|p| p.len()).sum::<usize>();
    let mut out = Vec::with_capacity(n + 4);
    out.extend_from_slice(&(n as u32).to_le_bytes());
    out.extend_from_slice(&kind.to_le_bytes());
    for p in parts {
        out.extend_from_slice(p);
    }
    out
}

// --- packs: ZIP entries by their VFS path ---------------------------------------------------

/// Entry name (no leading '/') -> the ZIP that holds it, from every ZIP in the profile's mods.
#[derive(Default)]
pub struct PackIndex {
    entries: HashMap<String, Arc<PathBuf>>,
    scanned: Vec<PathBuf>,
}

impl PackIndex {
    pub fn scan(&mut self, zips: &[PathBuf]) {
        for z in zips {
            if self.scanned.contains(z) {
                continue;
            }
            self.scanned.push(z.clone());
            let Ok(f) = File::open(z) else { continue };
            let Ok(archive) = zip::ZipArchive::new(BufReader::new(f)) else { continue };
            let path = Arc::new(z.clone());
            for name in archive.file_names() {
                if name.starts_with("earthng/") {
                    // first mounted wins, like the game's VFS for duplicate paths is not defined:
                    // a duplicate is recorded so the job can refuse it
                    self.entries.entry(name.to_string()).or_insert_with(|| path.clone());
                }
            }
        }
    }
    pub fn find(&self, vfs: &str) -> Option<Arc<PathBuf>> {
        self.entries.get(vfs.trim_start_matches('/')).cloned()
    }
}

/// Each worker keeps its own open archives (ZipArchive is not shared between threads).
#[derive(Default)]
pub struct Reader {
    open: HashMap<PathBuf, zip::ZipArchive<BufReader<File>>>,
}

impl Reader {
    pub fn read(&mut self, index: &Mutex<PackIndex>, vfs: &str) -> Result<Vec<u8>, String> {
        let zip_path = index.lock().unwrap().find(vfs).ok_or_else(|| format!("not in any pack: {vfs}"))?;
        if !self.open.contains_key(zip_path.as_path()) {
            let f = File::open(zip_path.as_path()).map_err(|e| e.to_string())?;
            let a = zip::ZipArchive::new(BufReader::new(f)).map_err(|e| e.to_string())?;
            self.open.insert(zip_path.as_path().to_path_buf(), a);
        }
        let a = self.open.get_mut(zip_path.as_path()).unwrap();
        let mut entry = a.by_name(vfs.trim_start_matches('/')).map_err(|e| e.to_string())?;
        let mut out = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut out).map_err(|e| e.to_string())?;
        Ok(out)
    }
}

// --- scheduler -------------------------------------------------------------------------------

pub struct Job {
    pub id: u64,
    pub epoch: u32,
    pub flags: u32,
    pub args: Vec<u8>,
    pub cancel: Arc<AtomicBool>,
    pub queued_at: Instant,
}

#[derive(PartialEq)]
struct Slot {
    priority: f64,
    id: u64,
    version: u64,
}
impl Eq for Slot {}
impl Ord for Slot {
    // BinaryHeap is a max-heap: the smallest priority (soonest ETA), then the oldest id, on top
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        o.priority.total_cmp(&self.priority).then(o.id.cmp(&self.id))
    }
}
impl PartialOrd for Slot {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(o))
    }
}

#[derive(Default)]
pub struct Queue {
    heap: BinaryHeap<Slot>,
    waiting: HashMap<u64, (Job, u64)>, // id -> (job, current version)
    running: HashMap<u64, Arc<AtomicBool>>,
    queued_bytes: usize,
    next_version: u64,
    closed: bool,
}

pub struct Limits {
    pub max_jobs: usize,
    pub max_bytes: usize,
}

pub struct Scheduler {
    q: Mutex<Queue>,
    cv: Condvar,
    pub limits: Limits,
}

impl Scheduler {
    pub fn new(limits: Limits) -> Self {
        Scheduler { q: Mutex::new(Queue::default()), cv: Condvar::new(), limits }
    }
    /// Err: the queue is full (the client builds the tile in Lua).
    pub fn push(&self, job: Job, priority: f64) -> Result<(), Job> {
        let mut q = self.q.lock().unwrap();
        if q.closed || q.waiting.len() >= self.limits.max_jobs || q.queued_bytes + job.args.len() > self.limits.max_bytes {
            return Err(job);
        }
        q.next_version += 1;
        let version = q.next_version;
        q.queued_bytes += job.args.len();
        q.heap.push(Slot { priority, id: job.id, version });
        q.waiting.insert(job.id, (job, version));
        drop(q);
        self.cv.notify_one();
        Ok(())
    }
    pub fn reprioritize(&self, id: u64, priority: f64) {
        let mut q = self.q.lock().unwrap();
        q.next_version += 1;
        let version = q.next_version;
        if let Some(entry) = q.waiting.get_mut(&id) {
            entry.1 = version;
            q.heap.push(Slot { priority, id, version });
        }
    }
    /// Cancel one job (id != 0) or every job of an older epoch (id == 0). Waiting jobs are
    /// dropped and returned; running ones see their flag at the next pause.
    pub fn cancel(&self, id: u64, below_epoch: u32) -> Vec<Job> {
        let mut q = self.q.lock().unwrap();
        let ids: Vec<u64> = if id != 0 {
            vec![id]
        } else {
            q.waiting.iter().filter(|(_, (j, _))| j.epoch < below_epoch).map(|(k, _)| *k).collect()
        };
        let mut dropped = Vec::new();
        for k in ids {
            if let Some((job, _)) = q.waiting.remove(&k) {
                q.queued_bytes -= job.args.len();
                dropped.push(job);
            } else if let Some(flag) = q.running.get(&k) {
                flag.store(true, Ordering::Relaxed);
            }
        }
        dropped
    }
    pub fn pop(&self) -> Option<Job> {
        let mut q = self.q.lock().unwrap();
        loop {
            if q.closed {
                return None;
            }
            while let Some(slot) = q.heap.pop() {
                let current = q.waiting.get(&slot.id).map(|e| e.1);
                if current == Some(slot.version) {
                    let (job, _) = q.waiting.remove(&slot.id).unwrap();
                    q.queued_bytes -= job.args.len();
                    q.running.insert(job.id, job.cancel.clone());
                    return Some(job);
                }
            }
            q = self.cv.wait(q).unwrap();
        }
    }
    pub fn finished(&self, id: u64) {
        self.q.lock().unwrap().running.remove(&id);
    }
    pub fn close(&self) -> Vec<Job> {
        let mut q = self.q.lock().unwrap();
        q.closed = true;
        for flag in q.running.values() {
            flag.store(true, Ordering::Relaxed);
        }
        q.heap.clear();
        q.queued_bytes = 0;
        let out = q.waiting.drain().map(|(_, (j, _))| j).collect();
        drop(q);
        self.cv.notify_all();
        out
    }
    pub fn depth(&self) -> (usize, usize) {
        let q = self.q.lock().unwrap();
        (q.waiting.len(), q.running.len())
    }
}

// --- shared session state --------------------------------------------------------------------

pub struct Shared {
    pub sources: Mutex<(u64, Arc<Vec<(String, Vec<u8>)>>)>,
    pub regions: Mutex<HashMap<String, Arc<Vec<u8>>>>,
    pub fs_false: Mutex<(u64, Vec<String>)>,
    pub packs: Mutex<PackIndex>,
    pub zips: Vec<PathBuf>,
    pub sched: Scheduler,
    pub out: Mutex<mpsc::Sender<Vec<u8>>>,
    pub alive: AtomicBool,
    pub started: Instant,
    pub memory_mb: AtomicU64,
}

fn now_ms(shared: &Shared) -> f64 {
    shared.started.elapsed().as_secs_f64() * 1000.0
}

// --- worker VM -------------------------------------------------------------------------------

struct Vm {
    lua: mlua::Lua,
    sources_gen: u64,
    fs_gen: u64,
}

const WORKER_MODULE: &str = "ge/extensions/e2r/bridge_worker";

fn make_vm(shared: &Arc<Shared>, cur: &Arc<Mutex<Option<Arc<AtomicBool>>>>, reader: &Arc<Mutex<Reader>>) -> mlua::Result<Vm> {
    let lua = unsafe { mlua::Lua::unsafe_new() };
    let (sources_gen, sources) = shared.sources.lock().unwrap().clone();
    let (fs_gen, fs_false) = shared.fs_false.lock().unwrap().clone();
    let g = lua.globals();
    // sources: module name -> chunk; a searcher in front of the file searchers
    let table = lua.create_table()?;
    for (name, src) in sources.iter() {
        table.set(name.as_str(), lua.create_string(src)?)?;
    }
    g.set("__bridge_sources", table)?;
    let falses = lua.create_table()?;
    for p in fs_false {
        falses.set(p, true)?;
    }
    g.set("__bridge_fs_false", falses)?;
    let s = shared.clone();
    g.set("host_clock", lua.create_function(move |_, ()| Ok(now_ms(&s)))?)?;
    let s = shared.clone();
    let c = cur.clone();
    g.set(
        "host_cancelled",
        lua.create_function(move |_, ()| {
            let job = c.lock().unwrap().as_ref().map(|f| f.load(Ordering::Relaxed)).unwrap_or(false);
            Ok(job || !s.alive.load(Ordering::Relaxed))
        })?,
    )?;
    let s = shared.clone();
    let r = reader.clone();
    g.set(
        "host_read",
        lua.create_function(move |lua, path: String| match r.lock().unwrap().read(&s.packs, &path) {
            Ok(bytes) => Ok((Some(lua.create_string(&bytes)?), None)),
            Err(e) => Ok((None, Some(e))),
        })?,
    )?;
    let s = shared.clone();
    g.set(
        "host_region",
        lua.create_function(move |lua, id: String| {
            let bytes = s.regions.lock().unwrap().get(&id).cloned();
            match bytes {
                Some(b) => Ok(Some(lua.create_string(b.as_slice())?)),
                None => Ok(None),
            }
        })?,
    )?;
    // GE Lua's own JIT options (BeamNG lua/ge/main.lua): with LuaJIT's defaults the generator's
    // long loops flush trace after trace and a worker ran a city tile ~2.5x slower than the game
    let jit = std::env::var("EARTHNG_BRIDGE_JIT")
        .unwrap_or_else(|_| "'minstitch=10000000', 'maxtrace=10000', 'maxmcode=8192', 'maxside=25', 'hotexit=100'".into());
    if jit != "default" {
        lua.load(format!("if jit then jit.opt.start({jit}) end")).exec()?;
    }
    lua.load(
        r#"
        table.insert(package.loaders or package.searchers, 2, function(name)
          local src = __bridge_sources[name]
          if not src then return '\n\tno bridge source ' .. name end
          return assert(load(src, '@' .. name))
        end)
        "#,
    )
    .exec()?;
    let worker: mlua::Table = lua.load(format!("return require('{WORKER_MODULE}')")).eval()?;
    g.set("__bridge_worker", worker)?;
    Ok(Vm { lua, sources_gen, fs_gen })
}

#[cfg(windows)]
mod os {
    unsafe extern "system" {
        fn GetCurrentThread() -> isize;
        fn SetThreadPriority(thread: isize, priority: i32) -> i32;
    }
    /// Workers yield the cores to the game's main and render threads first.
    pub fn below_normal() {
        unsafe {
            SetThreadPriority(GetCurrentThread(), -1);
        }
    }
}
#[cfg(not(windows))]
mod os {
    pub fn below_normal() {}
}

fn worker_loop(shared: Arc<Shared>, index: u32) {
    os::below_normal();
    let cur: Arc<Mutex<Option<Arc<AtomicBool>>>> = Arc::new(Mutex::new(None));
    let reader = Arc::new(Mutex::new(Reader::default()));
    let mut vm: Option<Vm> = None;
    while let Some(job) = shared.sched.pop() {
        let started = Instant::now();
        let queue_ms = job.queued_at.elapsed().as_secs_f64() * 1000.0;
        *cur.lock().unwrap() = Some(job.cancel.clone());
        let sources_gen = shared.sources.lock().unwrap().0;
        let fs_gen = shared.fs_false.lock().unwrap().0;
        if vm.as_ref().map(|v| v.sources_gen != sources_gen || v.fs_gen != fs_gen).unwrap_or(true) {
            vm = None;
        }
        let mut status = OK;
        let mut message = Vec::new();
        if vm.is_none() {
            match make_vm(&shared, &cur, &reader) {
                Ok(v) => vm = Some(v),
                Err(e) => {
                    status = FAILED;
                    message = format!("vm: {e}").into_bytes();
                }
            }
        }
        if let Some(v) = vm.as_ref() {
            let out = shared.out.lock().unwrap().clone();
            let id = job.id;
            let epoch = job.epoch;
            let emit = v.lua.create_function(move |_, (kind, bytes): (u32, mlua::String)| {
                let head = [id.to_le_bytes().as_slice(), epoch.to_le_bytes().as_slice(), kind.to_le_bytes().as_slice()].concat();
                let _ = out.send(frame(PART, &[&head, &bytes.as_bytes()]));
                Ok(())
            });
            let result: mlua::Result<mlua::String> = emit.and_then(|emit| {
                let worker: mlua::Table = v.lua.globals().get("__bridge_worker")?;
                let run: mlua::Function = worker.get("run")?;
                run.call((v.lua.create_string(&job.args)?, job.flags, emit))
            });
            match result {
                Ok(stats) => message = stats.as_bytes().to_vec(),
                Err(e) => {
                    let text = e.to_string();
                    status = if text.contains("e2r-bridge-cancelled") || job.cancel.load(Ordering::Relaxed) { CANCELLED } else { FAILED };
                    message = text.into_bytes();
                }
            }
            // a VM over its budget (block and grid caches, garbage) is dropped, never shared
            // the tile's garbage goes now, on this thread: four idle VMs holding a city tile's
            // heap each were +1.75 GB of the game's private memory (kyiv-q50-rust-1)
            let kb: f64 = v.lua.load("return collectgarbage('count')").eval().unwrap_or(0.0);
            let limit = shared.memory_mb.load(Ordering::Relaxed) as f64 * 1024.0;
            if kb > 192.0 * 1024.0 || kb > limit {
                let _ = v.lua.load("collectgarbage('collect')").exec();
                let kb: f64 = v.lua.load("return collectgarbage('count')").eval().unwrap_or(0.0);
                if kb > limit {
                    vm = None;
                }
            }
        }
        *cur.lock().unwrap() = None;
        shared.sched.finished(job.id);
        let run_ms = started.elapsed().as_secs_f64() * 1000.0;
        let head = [
            job.id.to_le_bytes().as_slice(),
            job.epoch.to_le_bytes().as_slice(),
            status.to_le_bytes().as_slice(),
            queue_ms.to_le_bytes().as_slice(),
            run_ms.to_le_bytes().as_slice(),
            index.to_le_bytes().as_slice(),
        ]
        .concat();
        let _ = shared.out.lock().unwrap().send(frame(DONE, &[&head, &message]));
    }
}

fn done_without_run(shared: &Shared, job: &Job, status: u32, why: &str) {
    let head = [
        job.id.to_le_bytes().as_slice(),
        job.epoch.to_le_bytes().as_slice(),
        status.to_le_bytes().as_slice(),
        0f64.to_le_bytes().as_slice(),
        0f64.to_le_bytes().as_slice(),
        u32::MAX.to_le_bytes().as_slice(),
    ]
    .concat();
    let _ = shared.out.lock().unwrap().send(frame(DONE, &[&head, why.as_bytes()]));
}

// --- session -------------------------------------------------------------------------------

fn read_frame(s: &mut impl Read) -> Result<(u32, Vec<u8>), String> {
    let mut head = [0u8; 8];
    s.read_exact(&mut head).map_err(|e| e.to_string())?;
    let n = u32::from_le_bytes(head[..4].try_into().unwrap()) as usize;
    if !(4..=MAX_FRAME).contains(&n) {
        return Err("frame length".into());
    }
    let kind = u32::from_le_bytes(head[4..].try_into().unwrap());
    let mut data = vec![0; n - 4];
    s.read_exact(&mut data).map_err(|e| e.to_string())?;
    Ok((kind, data))
}

pub struct Config {
    pub token: String,
    pub zips: Vec<PathBuf>,
    pub max_workers: u32,
}

/// The session now serving the game (id, a handle on its socket): a verified newer one shuts it
/// down, so a Lua reload in the game never waits for the old socket to be collected.
type Current = Mutex<Option<(u64, TcpStream)>>;

fn session(stream: TcpStream, cfg: &Config, current: &Current, me: u64) -> Result<(), String> {
    stream.set_nonblocking(false).map_err(|e| e.to_string())?;
    stream.set_nodelay(true).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(10))).map_err(|e| e.to_string())?;
    let mut input = stream.try_clone().map_err(|e| e.to_string())?;
    // HELLO first, with the token from the profile: anything else closes the connection
    let (kind, hello) = read_frame(&mut input)?;
    if kind != HELLO || hello.len() < 16 + cfg.token.len() || &hello[16..16 + cfg.token.len()] != cfg.token.as_bytes() {
        return Err("bad hello".into());
    }
    let version = u32at(&hello, 0)?;
    let workers = u32at(&hello, 4)?.clamp(1, cfg.max_workers);
    let memory_mb = u32at(&hello, 8)?.clamp(64, 4096);
    let max_jobs = u32at(&hello, 12)?.clamp(1, 256) as usize;
    if version != VERSION {
        return Err("protocol version".into());
    }
    input.set_read_timeout(None).map_err(|e| e.to_string())?;
    if let Ok(mine) = stream.try_clone() {
        let mut c = current.lock().unwrap();
        if let Some((_, old)) = c.take() {
            let _ = old.shutdown(std::net::Shutdown::Both);
        }
        *c = Some((me, mine));
    }
    let (tx, rx) = mpsc::channel::<Vec<u8>>();
    let shared = Arc::new(Shared {
        sources: Mutex::new((0, Arc::new(Vec::new()))),
        regions: Mutex::new(HashMap::new()),
        fs_false: Mutex::new((0, Vec::new())),
        packs: Mutex::new(PackIndex::default()),
        zips: cfg.zips.clone(),
        sched: Scheduler::new(Limits { max_jobs, max_bytes: 64 << 20 }),
        out: Mutex::new(tx),
        alive: AtomicBool::new(true),
        started: Instant::now(),
        memory_mb: AtomicU64::new(memory_mb as u64),
    });
    // the writer owns the socket's sending half; parts go out in the order they are made
    let mut output = stream.try_clone().map_err(|e| e.to_string())?;
    let writer = std::thread::Builder::new()
        .name("earthng-bridge-writer".into())
        .spawn(move || {
            for f in rx {
                if output.write_all(&f).is_err() {
                    break;
                }
            }
        })
        .map_err(|e| e.to_string())?;
    let _ = shared.out.lock().unwrap().send(frame(
        HELLO_OK,
        &[&VERSION.to_le_bytes(), &workers.to_le_bytes(), &std::process::id().to_le_bytes()],
    ));
    shared.packs.lock().unwrap().scan(&shared.zips);
    let mut pool = Vec::new();
    for k in 0..workers {
        let s = shared.clone();
        pool.push(
            std::thread::Builder::new()
                .name(format!("earthng-bridge-worker-{k}"))
                .stack_size(16 << 20)
                .spawn(move || worker_loop(s, k))
                .map_err(|e| e.to_string())?,
        );
    }
    let result = (|| -> Result<(), String> {
        loop {
            let (kind, data) = read_frame(&mut input)?;
            match kind {
                SOURCES => {
                    let mut list = Vec::new();
                    let mut p = 0;
                    while p < data.len() {
                        let n = u32at(&data, p)? as usize;
                        let name = String::from_utf8(data.get(p + 4..p + 4 + n).ok_or("name")?.to_vec()).map_err(|_| "name utf8")?;
                        p += 4 + n;
                        let m = u32at(&data, p)? as usize;
                        list.push((name, data.get(p + 4..p + 4 + m).ok_or("source")?.to_vec()));
                        p += 4 + m;
                    }
                    let mut s = shared.sources.lock().unwrap();
                    *s = (s.0 + 1, Arc::new(list));
                }
                REGION => {
                    let n = u32at(&data, 0)? as usize;
                    let id = String::from_utf8(data.get(4..4 + n).ok_or("region id")?.to_vec()).map_err(|_| "region utf8")?;
                    shared.regions.lock().unwrap().insert(id, Arc::new(data[4 + n..].to_vec()));
                }
                JOB => {
                    let job = Job {
                        id: u64at(&data, 0)?,
                        epoch: u32at(&data, 8)?,
                        flags: u32at(&data, 20)?,
                        args: data.get(24..).ok_or("job")?.to_vec(),
                        cancel: Arc::new(AtomicBool::new(false)),
                        queued_at: Instant::now(),
                    };
                    let priority = f64at(&data, 12)?;
                    if let Err(job) = shared.sched.push(job, priority) {
                        done_without_run(&shared, &job, BUSY, "queue full");
                    }
                }
                PRIORITY => shared.sched.reprioritize(u64at(&data, 0)?, f64at(&data, 8)?),
                CANCEL => {
                    for job in shared.sched.cancel(u64at(&data, 0)?, u32at(&data, 8)?) {
                        done_without_run(&shared, &job, CANCELLED, "cancelled before start");
                    }
                }
                FS_FALSE => {
                    let text = String::from_utf8_lossy(&data).to_string();
                    let mut f = shared.fs_false.lock().unwrap();
                    for p in text.split('\n').filter(|p| !p.is_empty()) {
                        if !f.1.iter().any(|q| q == p) {
                            f.1.push(p.to_string());
                        }
                    }
                    f.0 += 1;
                }
                BYE => return Ok(()),
                _ => return Err(format!("frame type {kind}")),
            }
        }
    })();
    // the game left (or closed the link): stop everything of this session
    shared.alive.store(false, Ordering::Relaxed);
    shared.sched.close();
    for t in pool {
        let _ = t.join();
    }
    drop(shared);
    let _ = writer.join();
    let _ = stream.shutdown(std::net::Shutdown::Both);
    let mut c = current.lock().unwrap();
    if c.as_ref().map(|x| x.0) == Some(me) {
        *c = None;
    }
    result
}

fn listener(dir: PathBuf, cfg: Config) -> std::io::Result<()> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    listener.set_nonblocking(true)?;
    std::fs::write(dir.join("bench-port.txt"), listener.local_addr()?.port().to_string())?;
    let mut checked = Instant::now();
    let cfg = Arc::new(cfg);
    let current: Arc<Current> = Arc::new(Mutex::new(None));
    let mut next = 0u64;
    loop {
        if checked.elapsed() > Duration::from_millis(500) {
            checked = Instant::now();
            if dir.join("bench-stop").exists() {
                if let Some((_, s)) = current.lock().unwrap().take() {
                    let _ = s.shutdown(std::net::Shutdown::Both);
                }
                return Ok(());
            }
        }
        match listener.accept() {
            Ok((stream, _)) => {
                next += 1;
                let (cfg, current, dir, me) = (cfg.clone(), current.clone(), dir.clone(), next);
                // each connection on its own thread: an unverified one cannot hold the port
                let _ = std::thread::Builder::new().name(format!("earthng-bridge-session-{me}")).spawn(move || {
                    let note = match session(stream, &cfg, &current, me) {
                        Ok(()) => format!("session {me} closed\n"),
                        Err(e) => format!("session {me} ended: {e}\n"),
                    };
                    if let Ok(mut log) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("bridge-log.txt")) {
                        let _ = log.write_all(note.as_bytes());
                    }
                });
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(20)),
            Err(e) => return Err(e),
        }
    }
}

fn token() -> String {
    use std::hash::{BuildHasher, Hasher};
    let mut out = String::new();
    for k in 0..2u64 {
        let mut h = std::collections::hash_map::RandomState::new().build_hasher();
        h.write_u64(k ^ std::process::id() as u64);
        h.write_u128(Instant::now().elapsed().as_nanos());
        out.push_str(&format!("{:016x}", h.finish()));
    }
    out
}

fn mods_zips(current: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for dir in [current.join("mods"), current.join("mods").join("repo")] {
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() {
                let p = e.path();
                if p.extension().map(|x| x.eq_ignore_ascii_case("zip")).unwrap_or(false) {
                    out.push(p);
                }
            }
        }
    }
    out.sort();
    out
}

/// The loader's entry: start the listener; marker is <user>/current/e2r_bridge/<name>.
#[unsafe(no_mangle)]
pub unsafe extern "system" fn earthng_probe(argument: *const u16) -> u32 {
    use std::os::windows::ffi::OsStringExt;
    if argument.is_null() {
        return 1;
    }
    let mut len = 0;
    while len < 32767 && unsafe { *argument.add(len) } != 0 {
        len += 1;
    }
    if len == 32767 {
        return 2;
    }
    let path = PathBuf::from(std::ffi::OsString::from_wide(unsafe { std::slice::from_raw_parts(argument, len) }));
    let Some(dir) = path.parent().map(Path::to_path_buf) else { return 3 };
    let Some(current) = dir.parent().map(Path::to_path_buf) else { return 3 };
    let cfg = Config { token: token(), zips: mods_zips(&current), max_workers: 8 };
    if std::fs::write(dir.join("bench-token.txt"), &cfg.token).is_err() {
        return 3;
    }
    if std::fs::write(&path, format!("earthng-bridge-v{VERSION}\npid={}\n", std::process::id())).is_err() {
        return 3;
    }
    let d = dir.clone();
    if std::thread::Builder::new()
        .name("earthng-bridge-listener".into())
        .spawn(move || {
            if let Err(e) = listener(d.clone(), cfg) {
                let _ = std::fs::write(d.join("bench-socket-error.txt"), e.to_string());
            }
        })
        .is_err()
    {
        return 4;
    }
    0
}

/// For offline tools and tests: run one job on a fresh VM, synchronously, with given sources.
pub fn run_offline(
    sources: Vec<(String, Vec<u8>)>,
    regions: HashMap<String, Vec<u8>>,
    zips: Vec<PathBuf>,
    args: &[u8],
    flags: u32,
) -> Result<(Vec<(u32, Vec<u8>)>, Vec<u8>), String> {
    let (tx, _rx) = mpsc::channel();
    let shared = Arc::new(Shared {
        sources: Mutex::new((1, Arc::new(sources))),
        regions: Mutex::new(regions.into_iter().map(|(k, v)| (k, Arc::new(v))).collect()),
        fs_false: Mutex::new((0, Vec::new())),
        packs: Mutex::new(PackIndex::default()),
        zips: zips.clone(),
        sched: Scheduler::new(Limits { max_jobs: 1, max_bytes: 1 << 30 }),
        out: Mutex::new(tx),
        alive: AtomicBool::new(true),
        started: Instant::now(),
        memory_mb: AtomicU64::new(4096),
    });
    shared.packs.lock().unwrap().scan(&zips);
    let cur = Arc::new(Mutex::new(None));
    let reader = Arc::new(Mutex::new(Reader::default()));
    let vm = make_vm(&shared, &cur, &reader).map_err(|e| e.to_string())?;
    let parts = Arc::new(Mutex::new(Vec::new()));
    let p = parts.clone();
    let emit = vm
        .lua
        .create_function(move |_, (kind, bytes): (u32, mlua::String)| {
            p.lock().unwrap().push((kind, bytes.as_bytes().to_vec()));
            Ok(())
        })
        .map_err(|e| e.to_string())?;
    let worker: mlua::Table = vm.lua.globals().get("__bridge_worker").map_err(|e| e.to_string())?;
    let run: mlua::Function = worker.get("run").map_err(|e| e.to_string())?;
    let stats: mlua::String = run
        .call((vm.lua.create_string(args).map_err(|e| e.to_string())?, flags, emit))
        .map_err(|e| e.to_string())?;
    let stats = stats.as_bytes().to_vec();
    let parts = std::mem::take(&mut *parts.lock().unwrap());
    Ok((parts, stats))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn job(id: u64, epoch: u32) -> Job {
        Job { id, epoch, flags: 0, args: vec![0; 10], cancel: Arc::new(AtomicBool::new(false)), queued_at: Instant::now() }
    }
    #[test]
    fn priority_then_id_and_reprioritize() {
        let s = Scheduler::new(Limits { max_jobs: 8, max_bytes: 1000 });
        s.push(job(1, 0), 5.0).map_err(|_| ()).unwrap();
        s.push(job(2, 0), 1.0).map_err(|_| ()).unwrap();
        s.push(job(3, 0), 1.0).map_err(|_| ()).unwrap();
        s.reprioritize(1, 0.5);
        assert_eq!(s.pop().unwrap().id, 1);
        assert_eq!(s.pop().unwrap().id, 2);
        assert_eq!(s.pop().unwrap().id, 3);
    }
    #[test]
    fn bounded_and_cancel_by_epoch() {
        let s = Scheduler::new(Limits { max_jobs: 2, max_bytes: 1000 });
        s.push(job(1, 1), 1.0).map_err(|_| ()).unwrap();
        s.push(job(2, 2), 1.0).map_err(|_| ()).unwrap();
        assert!(s.push(job(3, 2), 1.0).is_err());
        let dropped = s.cancel(0, 2);
        assert_eq!(dropped.len(), 1);
        assert_eq!(dropped[0].id, 1);
        assert_eq!(s.pop().unwrap().id, 2);
        // a running job is flagged, not removed
        let flag = Arc::new(AtomicBool::new(false));
        s.q.lock().unwrap().running.insert(9, flag.clone());
        assert!(s.cancel(9, 0).is_empty());
        assert!(flag.load(Ordering::Relaxed));
    }
    #[test]
    fn close_wakes_and_drains() {
        let s = Arc::new(Scheduler::new(Limits { max_jobs: 2, max_bytes: 1000 }));
        let t = {
            let s = s.clone();
            std::thread::spawn(move || s.pop().is_none())
        };
        std::thread::sleep(Duration::from_millis(50));
        s.close();
        assert!(t.join().unwrap());
        assert!(s.push(job(1, 0), 0.0).is_err());
    }
    #[test]
    fn vm_runs_sources_and_reads_regions() {
        let worker = br#"
          local M = {}
          function M.run(args, flags, emit)
            local region = host_region('r1')
            emit(1, args .. '|' .. tostring(flags) .. '|' .. region)
            local ffi = require('ffi')
            return tostring(ffi.sizeof('double')) .. (host_cancelled() and 'c' or 'n')
          end
          return M
        "#;
        let mut regions = HashMap::new();
        regions.insert("r1".to_string(), b"REG".to_vec());
        let (parts, stats) =
            run_offline(vec![(WORKER_MODULE.to_string(), worker.to_vec())], regions, vec![], b"abc", 7).unwrap();
        assert_eq!(parts, vec![(1, b"abc|7|REG".to_vec())]);
        assert_eq!(stats, b"8n");
    }
}
