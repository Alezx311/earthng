//! Offline harness for BLD.pieces port.
mod wall_geometry;
fn main()->Result<(),Box<dyn std::error::Error>> {
    let args:Vec<_>=std::env::args_os().collect();
    if args.len()!=3{return Err("usage: wall_geometry_cli REQUEST RESPONSE".into());}
    let input=std::fs::read(&args[1])?;
    let output=wall_geometry::batch(&input).map_err(std::io::Error::other)?;
    std::fs::write(&args[2],output)?;Ok(())
}
