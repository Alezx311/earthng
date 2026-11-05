//! The raw cut's selection rules, as earthng/osm_select.py states them.

/// osm_select.VERSION: recorded in every tile index.json.
pub const VERSION: u32 = 2;

/// Keys that tag no fact about the place (osm_select.META_KEYS).
pub const META_KEYS: [&[u8]; 6] = [b"created_by", b"source", b"note", b"fixme", b"FIXME", b"description"];

/// osm_select.LANDMARK_TAGS
const LANDMARK_TAGS: [(&[u8], &[&[u8]]); 10] = [
    (b"historic", &[b"monument", b"memorial", b"castle", b"ruins"]),
    (b"amenity", &[b"place_of_worship", b"university", b"theatre"]),
    (b"building", &[b"church", b"cathedral", b"stadium", b"train_station", b"university"]),
    (b"railway", &[b"station"]),
    (b"shop", &[b"mall"]),
    (b"leisure", &[b"park", b"stadium"]),
    (b"place", &[b"square"]),
    (b"man_made", &[b"bridge", b"tower", b"works"]),
    (b"tourism", &[b"museum", b"attraction"]),
    (b"", &[]),
];

/// tags.get(key): the first value of key, as osmium's TagList.get returns it.
pub fn get<'a>(tags: &'a [(Box<[u8]>, Box<[u8]>)], key: &[u8]) -> Option<&'a [u8]> {
    tags.iter().find(|(k, _)| &**k == key).map(|(_, v)| &**v)
}

/// osm_select.poi: any tag that is not a meta key.
pub fn poi(tags: &[(Box<[u8]>, Box<[u8]>)]) -> bool {
    tags.iter().any(|(k, _)| !META_KEYS.contains(&&**k))
}

/// osm_select.landmark_category(tags) is not None.
pub fn landmark(tags: &[(Box<[u8]>, Box<[u8]>)]) -> bool {
    LANDMARK_TAGS.iter().any(|(k, choices)| !k.is_empty() && get(tags, k).is_some_and(|v| choices.contains(&v)))
}

/// A relation the cut follows: restriction, multipolygon or landmark.
pub fn relevant_relation(tags: &[(Box<[u8]>, Box<[u8]>)]) -> bool {
    matches!(get(tags, b"type"), Some(b"restriction") | Some(b"multipolygon")) || landmark(tags)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(pairs: &[(&str, &str)]) -> Vec<(Box<[u8]>, Box<[u8]>)> {
        pairs.iter().map(|(k, v)| (k.as_bytes().into(), v.as_bytes().into())).collect()
    }

    #[test]
    fn poi_ignores_meta_keys() {
        assert!(!poi(&t(&[("created_by", "JOSM"), ("source", "survey")])));
        assert!(poi(&t(&[("source", "survey"), ("highway", "street_lamp")])));
        assert!(!poi(&t(&[])));
    }

    #[test]
    fn relations_followed() {
        assert!(relevant_relation(&t(&[("type", "multipolygon")])));
        assert!(relevant_relation(&t(&[("type", "route"), ("historic", "castle")])));
        assert!(!relevant_relation(&t(&[("type", "route"), ("historic", "wayside_cross")])));
    }
}
