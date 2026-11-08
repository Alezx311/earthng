//! Where the Python side lives. A release exe ends with its runtime ZIP and a trailer:
//! [zip][sha256 of zip: 32][zip length: u64 LE][MAGIC: 16]. The ZIP unpacks once into
//! %LOCALAPPDATA%\EarthNG\runtime\<first 16 hex of the sha>. A checkout build (no trailer) uses
//! the checkout: .venv's Python, earthng/ and app/ui on disk.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};

pub const MAGIC: &[u8; 16] = b"EARTHNG-RUNTIME1";
const TRAILER: u64 = 32 + 8 + 16;

#[derive(Debug, Clone)]
pub struct Runtime {
    /// the folder with earthng/, mod/, bin/ (a checkout or the unpacked runtime)
    pub code: PathBuf,
    pub python: PathBuf,
    pub ui: PathBuf,
    /// EARTHNG_HOME for the service: Some in a release, None in a checkout (it keeps its data)
    pub home: Option<PathBuf>,
}

impl Runtime {
    pub fn locate() -> Result<Runtime> {
        let exe = std::env::current_exe()?;
        if let Some((offset, len, sha)) = payload(&exe)? {
            let code = unpack(&exe, offset, len, &sha)?;
            let home = std::env::var_os("EARTHNG_HOME").map(PathBuf::from).unwrap_or_else(|| crate::local().join("data"));
            return Ok(Runtime { python: code.join("python").join("python.exe"), ui: code.join("app").join("ui"), code, home: Some(home) });
        }
        // a checkout: rust/target/<profile>/EarthNG.exe, or EARTHNG_CHECKOUT
        let start = std::env::var_os("EARTHNG_CHECKOUT").map(PathBuf::from).unwrap_or(exe);
        let root = start
            .ancestors()
            .find(|p| p.join("earthng").join("app_service.py").is_file())
            .map(Path::to_path_buf)
            .context("no runtime in this exe and no EarthNG checkout above it")?;
        let python = [root.join("python").join("python.exe"), root.join(".venv").join("Scripts").join("python.exe")]
            .into_iter()
            .find(|p| p.is_file())
            .context("the checkout has no .venv (Setup.bat)")?;
        Ok(Runtime { ui: root.join("app").join("ui"), python, home: std::env::var_os("EARTHNG_HOME").map(PathBuf::from), code: root })
    }
}

/// (offset, length, sha256) of the runtime ZIP appended to exe, if any.
pub fn payload(exe: &Path) -> Result<Option<(u64, u64, [u8; 32])>> {
    let mut f = File::open(exe)?;
    let size = f.metadata()?.len();
    if size < TRAILER {
        return Ok(None);
    }
    f.seek(SeekFrom::Start(size - TRAILER))?;
    let mut tail = [0u8; TRAILER as usize];
    f.read_exact(&mut tail)?;
    if &tail[40..56] != MAGIC {
        return Ok(None);
    }
    let mut sha = [0u8; 32];
    sha.copy_from_slice(&tail[..32]);
    let len = u64::from_le_bytes(tail[32..40].try_into().unwrap());
    if len > size - TRAILER {
        bail!("damaged runtime trailer");
    }
    Ok(Some((size - TRAILER - len, len, sha)))
}

/// A byte range of a file as a seekable reader (the ZIP inside the exe).
struct Window {
    file: File,
    start: u64,
    len: u64,
    pos: u64,
}

impl Read for Window {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let left = self.len.saturating_sub(self.pos);
        let n = (buf.len() as u64).min(left) as usize;
        if n == 0 {
            return Ok(0);
        }
        self.file.seek(SeekFrom::Start(self.start + self.pos))?;
        let got = self.file.read(&mut buf[..n])?;
        self.pos += got as u64;
        Ok(got)
    }
}

impl Seek for Window {
    fn seek(&mut self, to: SeekFrom) -> std::io::Result<u64> {
        let next = match to {
            SeekFrom::Start(p) => p as i64,
            SeekFrom::End(d) => self.len as i64 + d,
            SeekFrom::Current(d) => self.pos as i64 + d,
        };
        if next < 0 {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "seek before start"));
        }
        self.pos = next as u64;
        Ok(self.pos)
    }
}

fn unpack(exe: &Path, offset: u64, len: u64, sha: &[u8; 32]) -> Result<PathBuf> {
    let hex: String = sha[..8].iter().map(|b| format!("{b:02x}")).collect();
    let base = crate::local().join("runtime");
    let target = base.join(&hex);
    if target.join(".complete").is_file() {
        return Ok(target);
    }
    crate::log(&format!("unpacking runtime {hex} ({} MB)", len >> 20));
    let part = base.join(format!("{hex}.part"));
    let _ = std::fs::remove_dir_all(&part);
    std::fs::create_dir_all(&part)?;
    let window = Window { file: File::open(exe)?, start: offset, len, pos: 0 };
    let mut archive = zip::ZipArchive::new(std::io::BufReader::with_capacity(1 << 20, window)).context("runtime ZIP")?;
    archive.extract(&part).context("unpack runtime")?;
    std::fs::write(part.join(".complete"), &hex)?;
    let _ = std::fs::remove_dir_all(&target);
    std::fs::rename(&part, &target).context("publish runtime")?;
    // older versions' runtimes: their data stays in data/, only the code goes
    if let Ok(entries) = std::fs::read_dir(&base) {
        for entry in entries.flatten() {
            if entry.file_name().to_string_lossy() != hex {
                let _ = std::fs::remove_dir_all(entry.path());
            }
        }
    }
    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn payload_trailer_round_trip() {
        let dir = std::env::temp_dir().join(format!("earthng-rt-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let exe = dir.join("x.exe");
        let mut zip_bytes = Vec::new();
        {
            let mut w = zip::ZipWriter::new(std::io::Cursor::new(&mut zip_bytes));
            w.start_file("earthng/app_service.py", zip::write::SimpleFileOptions::default()).unwrap();
            w.write_all(b"print('hi')").unwrap();
            w.finish().unwrap();
        }
        let mut f = File::create(&exe).unwrap();
        f.write_all(b"MZ fake exe body").unwrap();
        f.write_all(&zip_bytes).unwrap();
        f.write_all(&[7u8; 32]).unwrap();
        f.write_all(&(zip_bytes.len() as u64).to_le_bytes()).unwrap();
        f.write_all(MAGIC).unwrap();
        drop(f);
        let (offset, len, sha) = payload(&exe).unwrap().unwrap();
        assert_eq!((offset, len, sha), (16, zip_bytes.len() as u64, [7u8; 32]));
        let window = Window { file: File::open(&exe).unwrap(), start: offset, len, pos: 0 };
        let mut archive = zip::ZipArchive::new(window).unwrap();
        let mut text = String::new();
        archive.by_name("earthng/app_service.py").unwrap().read_to_string(&mut text).unwrap();
        assert_eq!(text, "print('hi')");
        assert!(payload(&dir.join("x.exe").with_extension("none")).is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
