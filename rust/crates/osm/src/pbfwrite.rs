//! A small .osm.pbf writer: dense nodes, ways and relations without metadata (the tiles keep
//! ids, coordinates, tags and members; nothing downstream reads versions or timestamps).

use std::io::Write;

use flate2::Compression;
use flate2::write::ZlibEncoder;
use rustc_hash::FxHashMap;

/// Elements per primitive block (the format's recommended maximum).
const BLOCK: usize = 8000;

fn varint(buf: &mut Vec<u8>, mut v: u64) {
    while v >= 0x80 {
        buf.push((v as u8) | 0x80);
        v >>= 7;
    }
    buf.push(v as u8);
}

fn zigzag(v: i64) -> u64 {
    ((v << 1) ^ (v >> 63)) as u64
}

fn key(buf: &mut Vec<u8>, field: u32, wire: u32) {
    varint(buf, u64::from(field << 3 | wire));
}

fn bytes(buf: &mut Vec<u8>, field: u32, data: &[u8]) {
    key(buf, field, 2);
    varint(buf, data.len() as u64);
    buf.extend_from_slice(data);
}

fn int(buf: &mut Vec<u8>, field: u32, v: u64) {
    key(buf, field, 0);
    varint(buf, v);
}

fn packed<I: IntoIterator<Item = u64>>(buf: &mut Vec<u8>, field: u32, values: I, scratch: &mut Vec<u8>) {
    scratch.clear();
    for v in values {
        varint(scratch, v);
    }
    if !scratch.is_empty() {
        bytes(buf, field, scratch);
    }
}

/// Tags as raw bytes: (key, value) pairs.
pub type Tags = Box<[(Box<[u8]>, Box<[u8]>)]>;

pub struct NodeOut<'a> {
    pub id: i64,
    /// longitude, latitude in 1e-7 degrees
    pub x: i32,
    pub y: i32,
    pub tags: &'a [(Box<[u8]>, Box<[u8]>)],
}

pub struct WayOut<'a> {
    pub id: i64,
    pub refs: &'a [i64],
    pub tags: &'a [(Box<[u8]>, Box<[u8]>)],
}

pub struct MemberOut<'a> {
    /// 0 node, 1 way, 2 relation (the format's MemberType)
    pub kind: u8,
    pub id: i64,
    pub role: &'a [u8],
}

pub struct RelationOut<'a> {
    pub id: i64,
    pub members: &'a [MemberOut<'a>],
    pub tags: &'a [(Box<[u8]>, Box<[u8]>)],
}

#[derive(Default)]
struct Strings<'a> {
    index: FxHashMap<&'a [u8], u32>,
    list: Vec<&'a [u8]>,
}

impl<'a> Strings<'a> {
    fn new() -> Self {
        let mut s = Strings::default();
        s.list.push(b"");
        s.index.insert(b"", 0);
        s
    }
    fn id(&mut self, v: &'a [u8]) -> u32 {
        if let Some(&i) = self.index.get(v) {
            return i;
        }
        let i = self.list.len() as u32;
        self.list.push(v);
        self.index.insert(v, i);
        i
    }
    fn encode(&self, buf: &mut Vec<u8>) {
        let mut table = Vec::new();
        for s in &self.list {
            bytes(&mut table, 1, s);
        }
        bytes(buf, 1, &table);
    }
}

/// Builds a whole .osm.pbf file in memory.
pub struct PbfWriter {
    out: Vec<u8>,
    level: Compression,
}

impl PbfWriter {
    pub fn new(program: &str) -> Self {
        let mut w = PbfWriter { out: Vec::new(), level: Compression::new(6) };
        let mut header = Vec::new();
        bytes(&mut header, 4, b"OsmSchema-V0.6");
        bytes(&mut header, 4, b"DenseNodes");
        bytes(&mut header, 5, b"Sort.Type_then_ID");
        bytes(&mut header, 16, program.as_bytes());
        w.blob("OSMHeader", &header);
        w
    }

    fn blob(&mut self, kind: &str, raw: &[u8]) {
        let mut z = ZlibEncoder::new(Vec::with_capacity(raw.len() / 3), self.level);
        z.write_all(raw).expect("in-memory zlib");
        let data = z.finish().expect("in-memory zlib");
        let mut blob = Vec::with_capacity(data.len() + 16);
        int(&mut blob, 2, raw.len() as u64);
        bytes(&mut blob, 3, &data);
        let mut head = Vec::new();
        bytes(&mut head, 1, kind.as_bytes());
        int(&mut head, 3, blob.len() as u64);
        self.out.extend_from_slice(&(head.len() as u32).to_be_bytes());
        self.out.extend_from_slice(&head);
        self.out.extend_from_slice(&blob);
    }

    fn block(&mut self, strings: &Strings, group: &[u8]) {
        let mut block = Vec::with_capacity(group.len() + 1024);
        strings.encode(&mut block);
        bytes(&mut block, 2, group);
        self.blob("OSMData", &block);
    }

    pub fn nodes(&mut self, nodes: &[NodeOut]) {
        let mut scratch = Vec::new();
        for chunk in nodes.chunks(BLOCK) {
            let mut st = Strings::new();
            let mut kv: Vec<u64> = Vec::new();
            let tagged = chunk.iter().any(|n| !n.tags.is_empty());
            if tagged {
                for n in chunk {
                    for (k, v) in n.tags {
                        kv.push(u64::from(st.id(k)));
                        kv.push(u64::from(st.id(v)));
                    }
                    kv.push(0);
                }
            }
            let mut dense = Vec::new();
            let mut prev = 0i64;
            packed(&mut dense, 1, chunk.iter().map(|n| { let d = n.id - prev; prev = n.id; zigzag(d) }), &mut scratch);
            let mut prev = 0i64;
            packed(&mut dense, 8, chunk.iter().map(|n| { let d = i64::from(n.y) - prev; prev = i64::from(n.y); zigzag(d) }), &mut scratch);
            let mut prev = 0i64;
            packed(&mut dense, 9, chunk.iter().map(|n| { let d = i64::from(n.x) - prev; prev = i64::from(n.x); zigzag(d) }), &mut scratch);
            if tagged {
                packed(&mut dense, 10, kv.iter().copied(), &mut scratch);
            }
            let mut group = Vec::new();
            bytes(&mut group, 2, &dense);
            self.block(&st, &group);
        }
    }

    pub fn ways(&mut self, ways: &[WayOut]) {
        let mut scratch = Vec::new();
        for chunk in ways.chunks(BLOCK) {
            let mut st = Strings::new();
            let mut group = Vec::new();
            let mut msg = Vec::new();
            for w in chunk {
                msg.clear();
                int(&mut msg, 1, w.id as u64);
                let ks: Vec<u64> = w.tags.iter().map(|(k, _)| u64::from(st.id(k))).collect();
                let vs: Vec<u64> = w.tags.iter().map(|(_, v)| u64::from(st.id(v))).collect();
                packed(&mut msg, 2, ks, &mut scratch);
                packed(&mut msg, 3, vs, &mut scratch);
                let mut prev = 0i64;
                packed(&mut msg, 8, w.refs.iter().map(|&r| { let d = r - prev; prev = r; zigzag(d) }), &mut scratch);
                bytes(&mut group, 3, &msg);
            }
            self.block(&st, &group);
        }
    }

    pub fn relations(&mut self, relations: &[RelationOut]) {
        let mut scratch = Vec::new();
        for chunk in relations.chunks(BLOCK) {
            let mut st = Strings::new();
            let mut group = Vec::new();
            let mut msg = Vec::new();
            for r in chunk {
                msg.clear();
                int(&mut msg, 1, r.id as u64);
                let ks: Vec<u64> = r.tags.iter().map(|(k, _)| u64::from(st.id(k))).collect();
                let vs: Vec<u64> = r.tags.iter().map(|(_, v)| u64::from(st.id(v))).collect();
                packed(&mut msg, 2, ks, &mut scratch);
                packed(&mut msg, 3, vs, &mut scratch);
                let roles: Vec<u64> = r.members.iter().map(|m| u64::from(st.id(m.role))).collect();
                packed(&mut msg, 8, roles, &mut scratch);
                let mut prev = 0i64;
                packed(&mut msg, 9, r.members.iter().map(|m| { let d = m.id - prev; prev = m.id; zigzag(d) }), &mut scratch);
                packed(&mut msg, 10, r.members.iter().map(|m| u64::from(m.kind)), &mut scratch);
                bytes(&mut group, 4, &msg);
            }
            self.block(&st, &group);
        }
    }

    pub fn finish(self) -> Vec<u8> {
        self.out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zigzag_matches_protobuf() {
        assert_eq!(zigzag(0), 0);
        assert_eq!(zigzag(-1), 1);
        assert_eq!(zigzag(1), 2);
        assert_eq!(zigzag(-2), 3);
        assert_eq!(zigzag(i64::MAX), u64::MAX - 1);
    }

    #[test]
    fn round_trip_through_osmpbf() {
        let tags: Tags = vec![(b"highway".to_vec().into_boxed_slice(), b"residential".to_vec().into_boxed_slice())].into_boxed_slice();
        let none: Tags = Vec::new().into_boxed_slice();
        let mut w = PbfWriter::new("test");
        w.nodes(&[NodeOut { id: 5, x: 304_500_000, y: 504_500_000, tags: &none },
                  NodeOut { id: 9, x: -1, y: -900_000_000, tags: &tags }]);
        w.ways(&[WayOut { id: 7, refs: &[5, 9, 5], tags: &tags }]);
        let members = [MemberOut { kind: 1, id: 7, role: b"outer" }, MemberOut { kind: 0, id: 5, role: b"" }];
        w.relations(&[RelationOut { id: 3, members: &members, tags: &tags }]);
        let data = w.finish();
        let reader = osmpbf::ElementReader::new(std::io::Cursor::new(data));
        let mut seen = Vec::new();
        reader.for_each(|e| match e {
            osmpbf::Element::DenseNode(n) => seen.push(format!("n{} {} {} {}", n.id(), n.decimicro_lon(), n.decimicro_lat(), n.tags().count())),
            osmpbf::Element::Way(w) => seen.push(format!("w{} {:?}", w.id(), w.refs().collect::<Vec<_>>())),
            osmpbf::Element::Relation(r) => seen.push(format!("r{} {:?}", r.id(), r.members().map(|m| (m.member_id, m.role().unwrap().to_string())).collect::<Vec<_>>())),
            osmpbf::Element::Node(_) => {}
        }).unwrap();
        assert_eq!(seen, vec!["n5 304500000 504500000 0", "n9 -1 -900000000 1", "w7 [5, 9, 5]", r#"r3 [(7, "outer"), (5, "")]"#]);
    }
}
