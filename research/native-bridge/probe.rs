//! Deliberately small native loading probe. No BeamNG or Lua APIs are touched.
use std::{ffi::OsString, os::windows::ffi::OsStringExt, path::{Path, PathBuf}, time::Duration};

fn worker(dir: &Path) {
    // Proof of transport only. Single outstanding request; ready flag is written
    // after closing the payload, so the reader never sees a partial request.
    let ready = dir.join("bridge-request.ready");
    loop {
        if dir.join("bridge-stop").exists() { break; }
        if ready.exists() {
            let req = std::fs::read_to_string(dir.join("bridge-request.txt"));
            let _ = std::fs::remove_file(&ready);
            let answer = req.ok().and_then(|s| {
                let mut nums = s.split_whitespace();
                let id = nums.next()?.parse::<u32>().ok()?;
                let a = nums.next()?.parse::<u32>().ok()?;
                let b = nums.next()?.parse::<u32>().ok()?;
                if nums.next().is_some() { return None; }
                Some(format!("{} {} {}", id, u64::from(a) + u64::from(b), std::process::id()))
            }).unwrap_or_else(|| "error".into());
            if std::fs::write(dir.join("bridge-response.txt"), answer).is_ok() {
                let _ = std::fs::write(dir.join("bridge-response.ready"), b"ready");
            }
        }
        std::thread::sleep(Duration::from_millis(2));
    }
}

/// The loader starts this export in a remote thread after LoadLibraryW returned.
/// `argument` is a NUL-terminated UTF-16 path, valid for the duration of this call.
#[unsafe(no_mangle)]
pub unsafe extern "system" fn earthng_probe(argument: *const u16) -> u32 {
    if argument.is_null() { return 1; }
    let mut len = 0;
    while len < 32767 && unsafe { *argument.add(len) } != 0 { len += 1; }
    if len == 32767 { return 2; }
    let path = PathBuf::from(OsString::from_wide(unsafe { std::slice::from_raw_parts(argument, len) }));
    let Some(dir) = path.parent().map(Path::to_path_buf) else { return 3; };
    let value = format!("earthng-native-probe-v2\npid={}\n", std::process::id());
    if std::fs::write(path, value).is_err() { return 3; }
    if std::thread::Builder::new().name("earthng-bridge-probe".into()).spawn(move || worker(&dir)).is_err() {
        return 4;
    }
    0
}
