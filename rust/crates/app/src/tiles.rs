//! Background map tiles for the page: earthng://localhost/tile/<z>/<x>/<y>.png, fetched from the
//! OpenStreetMap tile server with this app's User-Agent (the policy asks for one) and kept on disk,
//! so a region looked at once opens offline and is not asked for again.

use std::io::Read;

const SERVER: &str = "https://tile.openstreetmap.org";
const MAX_AGE_DAYS: u64 = 30;

fn parse(rest: &str) -> Option<(u32, u32, u32)> {
    let rest = rest.strip_suffix(".png")?;
    let mut it = rest.split('/');
    let z: u32 = it.next()?.parse().ok()?;
    let x: u32 = it.next()?.parse().ok()?;
    let y: u32 = it.next()?.parse().ok()?;
    if it.next().is_some() || z > 19 || x >= 1 << z || y >= 1 << z {
        return None;
    }
    Some((z, x, y))
}

/// (status, body) for "<z>/<x>/<y>.png".
pub fn serve(rest: &str) -> (u16, Vec<u8>) {
    let Some((z, x, y)) = parse(rest) else {
        return (400, b"bad tile".to_vec());
    };
    let path = crate::local().join("cache").join("osm").join(z.to_string()).join(x.to_string()).join(format!("{y}.png"));
    let fresh = std::fs::metadata(&path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.elapsed().ok())
        .is_some_and(|age| age.as_secs() < MAX_AGE_DAYS * 86400);
    if fresh && let Ok(bytes) = std::fs::read(&path) {
        return (200, bytes);
    }
    match fetch(z, x, y) {
        Ok(bytes) => {
            if let Some(dir) = path.parent() {
                let _ = std::fs::create_dir_all(dir);
                let part = path.with_extension("part");
                if std::fs::write(&part, &bytes).is_ok() {
                    let _ = std::fs::rename(&part, &path);
                }
            }
            (200, bytes)
        }
        // offline: an old copy is better than a hole
        Err(e) => match std::fs::read(&path) {
            Ok(bytes) => (200, bytes),
            Err(_) => (502, e.into_bytes()),
        },
    }
}

fn fetch(z: u32, x: u32, y: u32) -> Result<Vec<u8>, String> {
    let agent = format!("EarthNG-MapBuilder/{} (+https://github.com/Alezx311/earthng)", crate::VERSION);
    let mut response = ureq::get(&format!("{SERVER}/{z}/{x}/{y}.png"))
        .header("User-Agent", &agent)
        .call()
        .map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    response.body_mut().as_reader().take(4 << 20).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::parse;

    #[test]
    fn tile_paths() {
        assert_eq!(parse("12/2393/1386.png"), Some((12, 2393, 1386)));
        assert_eq!(parse("1/2/0.png"), None);
        assert_eq!(parse("20/0/0.png"), None);
        assert_eq!(parse("3/1/1.jpg"), None);
        assert_eq!(parse("3/1/1/1.png"), None);
        assert_eq!(parse("../1/1.png"), None);
    }
}
