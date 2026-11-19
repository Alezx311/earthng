//! Replace the running EarthNG.exe with a downloaded build.
//!
//! Windows will not overwrite an exe it is running. The window checks the file in
//! %LOCALAPPDATA%\EarthNG\updates (Python already matched its sha256 to EarthNG.json), copies its
//! own code without the runtime ZIP to updates\apply-<pid>.exe, and exits. That copy waits until
//! this process is gone, moves the installed exe aside, puts the download in its place and starts
//! it. Maps and downloads live in data\ and in the BeamNG user folder, so they stay.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::runtime;

static STAGED: AtomicBool = AtomicBool::new(false);

pub fn stage() -> Result<()> {
    if STAGED.swap(true, Ordering::SeqCst) {
        bail!("EarthNG is already restarting");
    }
    match stage_inner() {
        Ok(()) => Ok(()),
        Err(err) => {
            STAGED.store(false, Ordering::SeqCst);
            Err(err)
        }
    }
}

fn stage_inner() -> Result<()> {
    let exe = std::env::current_exe().context("this program")?;
    if runtime::payload(&exe)?.is_none() {
        bail!("updates apply to the installed EarthNG.exe");
    }
    let updates = crate::local().join("updates");
    let (sha, size) = read_sidecar(&updates.join("EarthNG.json"))?;
    verify_release(&updates.join("EarthNG.exe"), &sha, size)?;
    cleanup();
    let helper = updates.join(format!("apply-{}.exe", std::process::id()));
    write_helper(&exe, &helper)?;
    let mut cmd = Command::new(&helper);
    cmd.arg("--apply-update")
        .arg(std::process::id().to_string())
        .arg(&sha)
        .arg(&exe)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0000_0008 | 0x0800_0000); // DETACHED_PROCESS | CREATE_NO_WINDOW
    }
    cmd.spawn().context("start the updater")?;
    Ok(())
}

/// Wait for the window to exit, then put the checked download in its place and start it.
pub fn apply(pid: u32, sha: &str, dest: &Path) -> Result<()> {
    if !wait_for_process(pid) {
        write_error("swap-failed");
        bail!("the running EarthNG did not exit");
    }
    let updates = crate::local().join("updates");
    let source = updates.join("EarthNG.exe");
    let (expected, size) = match read_sidecar(&updates.join("EarthNG.json")) {
        Ok(pair) => pair,
        Err(err) => {
            note_and_reopen(dest, "swap-failed");
            return Err(err);
        }
    };
    if expected != sha.to_ascii_lowercase() {
        note_and_reopen(dest, "swap-failed");
        bail!("update hash does not match the manifest");
    }
    let dest = match dest.canonicalize() {
        Ok(path) => path,
        Err(err) => {
            write_error("swap-failed");
            return Err(err).context("the installed exe");
        }
    };
    let updates_canon = updates.canonicalize().unwrap_or(updates);
    if !install_target_ok(&dest, &updates_canon) {
        write_error("swap-failed");
        bail!("refusing to replace {}", dest.display());
    }
    if let Err(err) = verify_release(&source, &expected, size) {
        note_and_reopen(&dest, "swap-failed");
        return Err(err);
    }
    let backup = match swap_in(&source, &dest) {
        Ok(path) => path,
        Err(err) => {
            note_and_reopen(&dest, "swap-failed");
            return Err(err);
        }
    };
    if let Err(err) = spawn_detached(&dest) {
        rollback(&dest, &backup);
        note_and_reopen(&dest, "start-failed");
        return Err(err);
    }
    let _ = std::fs::remove_file(&backup);
    let _ = std::fs::remove_file(&source);
    let _ = std::fs::remove_file(updates_canon.join("EarthNG.json"));
    let _ = std::fs::remove_file(crate::local().join("updates").join("error.txt"));
    Ok(())
}

/// Drop helper copies left by an earlier update. The running helper is a different file.
pub fn cleanup() {
    let Ok(entries) = std::fs::read_dir(crate::local().join("updates")) else { return };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("apply-") && name.ends_with(".exe") {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

fn note_and_reopen(dest: &Path, code: &str) {
    write_error(code);
    let _ = spawn_detached(dest);
}

fn write_error(code: &str) {
    let dir = crate::local().join("updates");
    let _ = std::fs::create_dir_all(&dir);
    let _ = std::fs::write(dir.join("error.txt"), code);
    crate::log(&format!("update: {code}"));
}

fn read_sidecar(path: &Path) -> Result<(String, u64)> {
    let value: Value = serde_json::from_slice(&std::fs::read(path).context("update manifest")?)?;
    if value.get("schema").and_then(Value::as_str) != Some("earthng-app-v1") {
        bail!("unexpected update manifest");
    }
    let sha = value.get("sha256").and_then(Value::as_str).context("sha256")?.to_ascii_lowercase();
    if sha.len() != 64 || !sha.chars().all(|c| c.is_ascii_hexdigit()) {
        bail!("bad update sha256");
    }
    let size = value.get("size").and_then(Value::as_u64).context("size")?;
    Ok((sha, size))
}

fn verify_release(path: &Path, sha: &str, size: u64) -> Result<()> {
    let meta = std::fs::metadata(path).with_context(|| format!("update file {}", path.display()))?;
    if meta.len() != size {
        bail!("downloaded size does not match the release");
    }
    let digest = sha256_file(path)?;
    if digest != sha.to_ascii_lowercase() {
        bail!("downloaded file does not match the release");
    }
    let mut file = File::open(path)?;
    let mut head = [0u8; 2];
    file.read_exact(&mut head)?;
    if &head != b"MZ" {
        bail!("downloaded file is not a Windows program");
    }
    file.seek(SeekFrom::End(-(runtime::MAGIC.len() as i64)))?;
    let mut tail = [0u8; 16];
    file.read_exact(&mut tail)?;
    if &tail != runtime::MAGIC {
        bail!("downloaded file is not an EarthNG build");
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String> {
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 1 << 20];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finalize().iter().map(|byte| format!("{byte:02x}")).collect())
}

fn install_target_ok(dest: &Path, updates: &Path) -> bool {
    dest.file_name().is_some_and(|name| name == "EarthNG.exe") && !dest.starts_with(updates)
}

fn backup_path(dest: &Path) -> PathBuf {
    let name = dest.file_name().and_then(|s| s.to_str()).unwrap_or("EarthNG.exe");
    dest.with_file_name(format!("{name}.previous"))
}

fn swap_in(source: &Path, dest: &Path) -> Result<PathBuf> {
    let backup = backup_path(dest);
    if backup.exists() {
        io_retry("remove the previous backup", || std::fs::remove_file(&backup))?;
    }
    io_retry("move the installed exe aside", || std::fs::rename(dest, &backup))?;
    if let Err(err) = io_retry("copy the new exe", || {
        std::fs::copy(source, dest)?;
        Ok(())
    }) {
        let _ = std::fs::rename(&backup, dest);
        return Err(err);
    }
    Ok(backup)
}

fn rollback(dest: &Path, backup: &Path) {
    let _ = std::fs::remove_file(dest);
    let _ = std::fs::rename(backup, dest);
}

fn io_retry(what: &str, mut op: impl FnMut() -> std::io::Result<()>) -> Result<()> {
    let mut last = None;
    for attempt in 0..40 {
        match op() {
            Ok(()) => return Ok(()),
            Err(err) => {
                last = Some(err);
                if attempt + 1 != 40 {
                    std::thread::sleep(Duration::from_millis(250));
                }
            }
        }
    }
    Err(anyhow::Error::from(last.unwrap())).context(what.to_string())
}

fn spawn_detached(dest: &Path) -> Result<()> {
    let mut cmd = Command::new(dest);
    if let Some(dir) = dest.parent() {
        cmd.current_dir(dir);
    }
    cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0000_0008 | 0x0800_0000); // DETACHED_PROCESS | CREATE_NO_WINDOW
    }
    cmd.spawn().context("start EarthNG")?;
    Ok(())
}

fn write_helper(exe: &Path, dest: &Path) -> Result<()> {
    let len = match runtime::payload(exe)? {
        Some((offset, _, _)) if offset >= 64 => offset,
        _ => std::fs::metadata(exe)?.len(),
    };
    if let Some(dir) = dest.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let mut input = File::open(exe)?;
    let mut output = File::create(dest)?;
    let mut left = len;
    let mut buf = [0u8; 1 << 20];
    while left > 0 {
        let want = (buf.len() as u64).min(left) as usize;
        let n = input.read(&mut buf[..want])?;
        if n == 0 {
            bail!("the installed exe is shorter than its runtime trailer");
        }
        output.write_all(&buf[..n])?;
        left -= n as u64;
    }
    Ok(())
}

fn wait_for_process(pid: u32) -> bool {
    #[cfg(windows)]
    {
        wait_for_process_win(pid)
    }
    #[cfg(not(windows))]
    {
        let _ = pid;
        true
    }
}

#[cfg(windows)]
unsafe extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut core::ffi::c_void;
    fn WaitForSingleObject(handle: *mut core::ffi::c_void, millis: u32) -> u32;
    fn CloseHandle(handle: *mut core::ffi::c_void) -> i32;
}

#[cfg(windows)]
fn wait_for_process_win(pid: u32) -> bool {
    const SYNCHRONIZE: u32 = 0x0010_0000;
    const WAIT_TIMEOUT: u32 = 0x0000_0102;
    const WAIT_FAILED: u32 = 0xFFFF_FFFF;
    unsafe {
        let handle = OpenProcess(SYNCHRONIZE, 0, pid);
        if handle.is_null() {
            return true;
        }
        let mut waited = 0u32;
        let gone = loop {
            let state = WaitForSingleObject(handle, 200);
            if state == WAIT_FAILED {
                break false;
            }
            if state != WAIT_TIMEOUT {
                break true;
            }
            waited += 200;
            if waited >= 60_000 {
                break false;
            }
        };
        CloseHandle(handle);
        gone
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("earthng-up-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn swap_replaces_the_exe_and_rollback_restores_it() {
        let dir = scratch("swap");
        let dest = dir.join("EarthNG.exe");
        let source = dir.join("new.exe");
        std::fs::write(&dest, b"old-bytes").unwrap();
        std::fs::write(&source, b"new-bytes").unwrap();
        let backup = swap_in(&source, &dest).unwrap();
        assert_eq!(std::fs::read(&dest).unwrap(), b"new-bytes");
        assert_eq!(std::fs::read(&backup).unwrap(), b"old-bytes");
        rollback(&dest, &backup);
        assert_eq!(std::fs::read(&dest).unwrap(), b"old-bytes");
        assert!(!backup.exists());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_different_hash_is_not_a_release_file() {
        let dir = scratch("hash");
        let path = dir.join("EarthNG.exe");
        let mut bytes = b"MZ".to_vec();
        bytes.extend([1u8; 32]);
        bytes.extend(runtime::MAGIC);
        std::fs::write(&path, &bytes).unwrap();
        let sha = sha256_file(&path).unwrap();
        verify_release(&path, &sha, bytes.len() as u64).unwrap();
        assert!(verify_release(&path, &"ab".repeat(32), bytes.len() as u64).is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_updater_only_replaces_an_exe_outside_the_update_folder() {
        let updates = Path::new(r"C:\Users\me\AppData\Local\EarthNG\updates");
        assert!(install_target_ok(Path::new(r"C:\Games\EarthNG.exe"), updates));
        assert!(!install_target_ok(updates.join("EarthNG.exe").as_path(), updates));
        assert!(!install_target_ok(Path::new(r"C:\Games\other.exe"), updates));
    }

    #[test]
    fn sha256_of_hello() {
        let dir = scratch("hello");
        let path = dir.join("hello");
        std::fs::write(&path, b"hello").unwrap();
        assert_eq!(
            sha256_file(&path).unwrap(),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
