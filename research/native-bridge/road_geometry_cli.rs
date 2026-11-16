//! Offline harness for the exact strip-normal/length kernel.
mod road_geometry;
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().collect();
    if args.len() != 3 { return Err("usage: road_geometry_cli REQUEST RESPONSE".into()); }
    let input=std::fs::read(&args[1])?;
    let output=road_geometry::batch(&input).map_err(std::io::Error::other)?;
    std::fs::write(&args[2],output)?;
    Ok(())
}
