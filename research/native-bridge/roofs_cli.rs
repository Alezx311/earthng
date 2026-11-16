//! Offline parity/CPU harness for roofs.rs. The live bridge uses the same batch function.
mod roofs;
fn main() -> Result<(),Box<dyn std::error::Error>> {
    let args:Vec<_>=std::env::args_os().collect();
    if args.len()!=3{return Err("usage: roofs_cli REQUEST.bin RESPONSE.bin".into());}
    let input=std::fs::read(&args[1])?;
    let output=roofs::batch(&input).map_err(std::io::Error::other)?;
    std::fs::write(&args[2],output)?;
    Ok(())
}
