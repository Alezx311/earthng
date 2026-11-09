fn main() {
    println!("cargo:rerun-if-changed=icon.ico");
    #[cfg(windows)]
    winresource::WindowsResource::new()
        .set_icon("icon.ico")
        .compile()
        .expect("embed the EarthNG executable icon");
}
