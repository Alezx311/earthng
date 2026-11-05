//! EarthNG Map Builder: pack building steps, one subcommand each.

use std::path::PathBuf;

use anyhow::Result;
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "earthng-mapbuilder", version, about = "EarthNG Map Builder")]
struct Cli {
    /// worker threads (default: all cores)
    #[arg(long, global = true)]
    threads: Option<usize>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Cut an .osm.pbf into the static tile archive (earthng/osm_tiles.py's format)
    Cut {
        pbf: PathBuf,
        /// new directory
        #[arg(long)]
        out: PathBuf,
        /// declared coverage of the package (west south east north) when the header has none,
        /// or to cut only part of the file
        #[arg(long, num_args = 4, allow_negative_numbers = true, value_names = ["W", "S", "E", "N"])]
        package_box: Option<Vec<f64>>,
    },
    /// Routing graphs of every region of a pack ZIP (earthng/build_routing.py's files):
    /// <out>/<region>.bin, one JSON line per region on stdout
    Routing {
        pack: PathBuf,
        #[arg(long)]
        out: PathBuf,
        /// only these region ids
        #[arg(long)]
        region: Vec<String>,
    },
    /// Settlement nodes and main roads of a PBF for earthng/build_map.py: places as JSON lines
    /// [lat, lon, [[k, v], ...]], roads as (u8 rank, u32 n, n x (lon, lat) f64)
    MapSource {
        pbf: PathBuf,
        #[arg(long)]
        places: PathBuf,
        #[arg(long)]
        roads: PathBuf,
    },
    /// Compile cells as earthng/build_country.compile_cell (task JSON from native_tool.compile_cells):
    /// per cell i64 i, i64 j, u8 status (0 payload, 2 left to Python), u32 roads, u32 n, n bytes
    Compile {
        task: PathBuf,
        #[arg(long)]
        out: PathBuf,
    },
    /// Build one raw OSM tile's scene as fast_sources.Store.build_scene and write_scene do. Input on
    /// stdin from native_tool.build_scene: u32 length + task JSON, then osmium's areas. Prints
    /// "ok <records>" or "python <reason>" (the tile left to Python, nothing written)
    Scene {
        #[arg(long)]
        out: PathBuf,
    },
    /// Encode cells dumped as JSON lines ({"origin": [x, y], "cell": {...}}) into hex lines
    /// (a check against earthng/country_format.py)
    #[command(hide = true)]
    EncodeCells { input: PathBuf, output: PathBuf },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    if let Some(n) = cli.threads {
        rayon::ThreadPoolBuilder::new().num_threads(n).build_global()?;
    }
    let emit = |line: String| println!("{line}");
    match cli.command {
        Command::Cut { pbf, out, package_box } => {
            let package_box = package_box.map(|b| [b[0], b[1], b[2], b[3]]);
            osm::cut::cut(&pbf, &out, package_box, &emit)?;
        }
        Command::MapSource { pbf, places, roads } => {
            let found = osm::mapsrc::extract(&pbf, &|line| eprintln!("{line}"))?;
            osm::mapsrc::write(&found, &places, &roads)?;
            println!("{}", serde_json::json!({"places": found.places.len(), "roads": found.roads.len(), "skipped": found.skipped}));
        }
        Command::Compile { task, out } => compile(&task, &out)?,
        Command::Scene { out } => scene(&out)?,
        Command::EncodeCells { input, output } => encode_cells(&input, &output)?,
        Command::Routing { pack, out, region } => routing(&pack, &out, &region)?,
    }
    Ok(())
}

fn scene(out: &std::path::Path) -> Result<()> {
    let t = std::time::Instant::now();
    let (task, areas) = cells::scenebuild::read_input(std::io::stdin().lock())?;
    match cells::scenebuild::build(&task, areas)? {
        cells::scenebuild::Outcome::Done(data, n) => {
            std::fs::write(out, data)?;
            if std::env::var_os("EARTHNG_SCENE_PROFILE").is_some() {
                eprintln!("scene: {n} records in {:.3} s", t.elapsed().as_secs_f64());
            }
            println!("ok {n}");
        }
        cells::scenebuild::Outcome::Python(why) => println!("python {why}"),
    }
    Ok(())
}

fn encode_cells(input: &std::path::Path, output: &std::path::Path) -> Result<()> {
    use std::io::{BufRead, Write};
    #[derive(serde::Deserialize)]
    struct Item {
        origin: [f64; 2],
        cell: pack::format::Cell,
    }
    let mut out = std::io::BufWriter::new(std::fs::File::create(output)?);
    let t = std::time::Instant::now();
    let (mut n, mut bytes) = (0, 0);
    for line in std::io::BufReader::new(std::fs::File::open(input)?).lines() {
        let item: Item = serde_json::from_str(&line?)?;
        let data = pack::format::encode_cell(&item.cell, item.origin)?;
        n += 1;
        bytes += data.len();
        for b in &data {
            write!(out, "{b:02x}")?;
        }
        writeln!(out)?;
    }
    println!("{n} cells, {bytes} bytes in {:.3} s", t.elapsed().as_secs_f64());
    Ok(())
}

/// "<bi>_<bj>.bin" at the end of a block member's name.
fn block_of(name: &str) -> Option<(i64, i64)> {
    let file = name.rsplit('/').next()?.strip_suffix(".bin")?;
    let (a, b) = file.split_once('_')?;
    // build_routing.BLOCK_NAME: -?\d+ each
    let ok = |t: &str| {
        let digits = t.strip_prefix('-').unwrap_or(t);
        !digits.is_empty() && digits.bytes().all(|c| c.is_ascii_digit())
    };
    if !ok(a) || !ok(b) {
        return None;
    }
    Some((a.parse().ok()?, b.parse().ok()?))
}

fn routing(pack: &std::path::Path, out: &std::path::Path, only: &[String]) -> Result<()> {
    use anyhow::Context;
    use rayon::prelude::*;
    use std::io::Read;
    let file = std::fs::File::open(pack).with_context(|| format!("open {}", pack.display()))?;
    let archive = zip::ZipArchive::new(file)?;
    // central directory order, as Python's namelist(): the roads keep the order Python reads them
    let names: Vec<String> = (0..archive.len()).filter_map(|k| archive.name_for_index(k).map(str::to_string)).collect();
    let mut regions = Vec::new();
    for name in &names {
        if let Some(rest) = name.strip_prefix("earthng/countries/")
            && let Some(prefix_end) = rest.find("/regions/")
        {
            let tail = &rest[prefix_end + "/regions/".len()..];
            if let Some(region) = tail.strip_suffix("/manifest.json")
                && !region.is_empty() && !region.contains('/')
                && !rest[..prefix_end].contains('/')
            {
                let prefix = name[..name.len() - "manifest.json".len()].to_string();
                if only.is_empty() || only.iter().any(|r| r == region) {
                    regions.push((region.to_string(), prefix));
                }
            }
        }
    }
    regions.sort();
    std::fs::create_dir_all(out)?;
    let read = |name: &str| -> Result<Vec<u8>> {
        let mut archive = zip::ZipArchive::new(std::fs::File::open(pack)?)?;
        let mut entry = archive.by_name(name)?;
        let mut data = Vec::with_capacity(entry.size() as usize);
        entry.read_to_end(&mut data)?;
        Ok(data)
    };
    let results: Vec<Result<String>> = regions
        .par_iter()
        .map(|(region, prefix)| -> Result<String> {
            let t = std::time::Instant::now();
            let manifest: serde_json::Value = serde_json::from_slice(&read(&format!("{prefix}manifest.json"))?)?;
            let cell = manifest.get("cellSize").and_then(|v| v.as_f64()).unwrap_or(1000.0);
            let block = manifest.get("blockCells").and_then(|v| v.as_i64()).unwrap_or(pack::format::BLOCK);
            let blocks: Vec<(&String, (i64, i64))> = names
                .iter()
                .filter(|n| n.starts_with(&format!("{prefix}blocks/")))
                .filter_map(|n| block_of(n).map(|b| (n, b)))
                .collect();
            let decoded: Vec<Result<Vec<pack::format::DecodedRoad>>> = blocks
                .par_iter()
                .map(|(name, (bi, bj))| -> Result<Vec<pack::format::DecodedRoad>> {
                    let data = read(name)?;
                    let mut roads = Vec::new();
                    for (slot, start, end) in pack::format::decode_block(&data)? {
                        let (i, j) = (bi * block + slot as i64 % block, bj * block + slot as i64 / block);
                        roads.extend(pack::format::decode_roads(&data, [i as f64 * cell, j as f64 * cell], start, end)?);
                    }
                    Ok(roads)
                })
                .collect();
            let mut all = Vec::new();
            for d in decoded {
                all.push(d?);
            }
            let g = pack::routing::graph(all.iter().flatten())?;
            let data = pack::routing::encode(&g)?;
            std::fs::write(out.join(format!("{region}.bin")), &data)?;
            Ok(serde_json::json!({"region": region, "nodes": g.nodes.len(), "edges": g.edges.len(),
                                  "bytes": data.len(), "seconds": (t.elapsed().as_secs_f64() * 10.0).round() / 10.0})
                .to_string())
        })
        .collect();
    for r in results {
        println!("{}", r?);
    }
    Ok(())
}

fn compile(task: &std::path::Path, out: &std::path::Path) -> Result<()> {
    use std::io::Write;
    #[derive(serde::Deserialize)]
    struct Task {
        geos: PathBuf,
        #[serde(flatten)]
        config: cells::compile::Config,
        cells: Vec<cells::compile::CellTask>,
    }
    let task: Task = serde_json::from_slice(&std::fs::read(task)?)?;
    cells::geos::load(&task.geos)?;
    let t = std::time::Instant::now();
    let outcomes = cells::compile::run(task.config, &task.cells)?;
    let mut file = std::io::BufWriter::new(std::fs::File::create(out)?);
    let mut left = 0;
    for (cell, outcome) in task.cells.iter().zip(&outcomes) {
        let (status, roads, body): (u8, usize, &[u8]) = match outcome {
            cells::compile::Outcome::Done { payload, roads } => (0, *roads, payload),
            cells::compile::Outcome::Python(reason) => {
                left += 1;
                (2, 0, reason.as_bytes())
            }
        };
        file.write_all(&cell.i.to_le_bytes())?;
        file.write_all(&cell.j.to_le_bytes())?;
        file.write_all(&[status])?;
        file.write_all(&(roads as u32).to_le_bytes())?;
        file.write_all(&(body.len() as u32).to_le_bytes())?;
        file.write_all(body)?;
    }
    file.flush()?;
    eprintln!("cells: {} compiled, {} left to Python ({:.2} s)", outcomes.len() - left, left, t.elapsed().as_secs_f64());
    Ok(())
}
