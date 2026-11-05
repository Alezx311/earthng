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
    }
    Ok(())
}
