//! cargo run --release -p pack --example egb3 -- <v2 block> <v3 block out>
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let data = std::fs::read(&args[1]).expect("read v2 block");
    let t = std::time::Instant::now();
    let v3 = pack::fixed::transcode_block(&data).expect("transcode");
    eprintln!("{} -> {} bytes in {:?}", data.len(), v3.len(), t.elapsed());
    std::fs::write(&args[2], v3).expect("write v3 block");
}
