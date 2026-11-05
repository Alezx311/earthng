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
        Command::EncodeCells { input, output } => encode_cells(&input, &output)?,
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
