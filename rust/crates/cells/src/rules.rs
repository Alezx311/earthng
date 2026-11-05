//! The tag rules Store.build_scene applies, in Python's control flow: retail.py (kind, brand,
//! enriched, post_type), fast_style.py (ground_kind, line_kind, point_kind, rail_tags, poi) and
//! nature.ground_kind. The sets and tables they read come from Python (native_tool.scene_rules),
//! so only the branching lives here; native_tool.RULES fingerprints the Python sources this
//! mirrors and turns native scenes off when one of them changes.

use std::collections::{HashMap, HashSet};

use serde::Deserialize;

use crate::pytext;

/// Reading tags as Python does: a dict, or osmium's TagList (its get finds the first pair).
pub trait Get {
    fn get(&self, key: &str) -> Option<&str>;
    fn has(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
}

/// An osmium TagList: the pairs as the file has them.
pub struct Raw<'a>(pub &'a [(&'a str, &'a str)]);

impl Get for Raw<'_> {
    fn get(&self, key: &str) -> Option<&str> {
        self.0.iter().find(|(k, _)| *k == key).map(|(_, v)| *v)
    }
}

/// A Python dict of str -> str, in insertion order.
#[derive(Clone, Debug, Default)]
pub struct Tags(pub Vec<(String, String)>);

impl Get for Tags {
    fn get(&self, key: &str) -> Option<&str> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }
}

impl Tags {
    /// dict(taglist): a key keeps its first place and its last value.
    pub fn dict(pairs: &[(&str, &str)]) -> Tags {
        let mut t = Tags(Vec::with_capacity(pairs.len()));
        for (k, v) in pairs {
            t.set(k, v);
        }
        t
    }
    pub fn set(&mut self, key: &str, value: &str) {
        match self.0.iter_mut().find(|(k, _)| k == key) {
            Some(slot) => slot.1 = value.to_string(),
            None => self.0.push((key.to_string(), value.to_string())),
        }
    }
    pub fn remove(&mut self, key: &str) {
        self.0.retain(|(k, _)| k != key);
    }
    pub fn setdefault(&mut self, key: &str, value: &str) {
        if !self.has(key) {
            self.0.push((key.to_string(), value.to_string()));
        }
    }
}

fn is(v: Option<&str>, s: &str) -> bool {
    v == Some(s)
}

fn within(v: Option<&str>, set: &HashSet<String>) -> bool {
    v.is_some_and(|v| set.contains(v))
}

/// `tags.get(k) in (None, 'no')`, osmium style
fn none_or_no(v: Option<&str>) -> bool {
    matches!(v, None | Some("no"))
}

#[derive(Deserialize)]
pub struct Rules {
    // retail.py
    pub lookup: HashMap<String, String>,
    pub wikidata: HashMap<String, String>,
    pub fuel: HashSet<String>,
    pub networks: HashSet<String>,
    pub food_shops: HashSet<String>,
    pub service_amenity: HashSet<String>,
    pub service_shops: HashSet<String>,
    pub names: Vec<String>,
    pub says: HashSet<String>,
    // fast_style.py
    pub point_keys: Vec<String>,
    pub islands: Vec<(String, String)>,
    pub fields: HashSet<String>,
    pub hard_fields: HashSet<String>,
    pub sites: HashSet<String>,
    pub paved: HashSet<String>,
    pub woods: HashSet<String>,
    pub parks: HashSet<String>,
    pub paths: HashSet<String>,
    pub rails: HashSet<String>,
    pub rail_tags: Vec<String>,
    pub unmarked: HashSet<String>,
    pub entrances: HashSet<String>,
    pub pois: bool,
    pub poi_amenity: HashSet<String>,
    pub poi_not: HashSet<String>,
    pub doors: HashSet<String>,
    // fast_sources.py
    pub part_tags: Vec<String>,
    #[serde(skip)]
    named: std::cell::RefCell<HashMap<String, Option<String>>>,
}

impl Rules {
    // ---- retail.py ----

    fn named(&self, value: Option<&str>) -> Option<String> {
        let value = value.filter(|v| !v.is_empty())?;
        if let Some(hit) = self.named.borrow().get(value) {
            return hit.clone();
        }
        let found = self.named_uncached(value);
        self.named.borrow_mut().insert(value.to_string(), found.clone());
        found
    }

    fn named_uncached(&self, value: &str) -> Option<String> {
        let normalized = pytext::key(value);
        if let Some(b) = self.lookup.get(&normalized) {
            return Some(b.clone());
        }
        // re.sub(r'(?:no)?[0-9]+$', '', normalized): a branch's number after the name
        let digits = normalized.len() - normalized.trim_end_matches(|c: char| c.is_ascii_digit()).len();
        if digits > 0 {
            let mut cut = &normalized[..normalized.len() - digits];
            if let Some(s) = cut.strip_suffix("no") {
                cut = s;
            }
            if let Some(b) = self.lookup.get(cut) {
                return Some(b.clone());
            }
        }
        if nova_poshta_branch(&normalized) {
            return Some("nova_poshta".into());
        }
        None
    }

    fn recognized(&self, t: &Tags) -> Option<String> {
        if t.0.iter().all(|(k, _)| !self.says.contains(k)) {
            return None;
        }
        for field in ["brand:wikidata", "operator:wikidata"] {
            let v = t.get(field);
            if v == Some("Q38076") {
                return Some("mcdonalds".into());
            }
            if matches!(v, Some("Q12133863" | "Q118613846")) {
                return Some("nova_poshta".into());
            }
            if let Some(b) = v.and_then(|v| self.wikidata.get(v)) {
                return Some(b.clone());
            }
        }
        for field in &self.names {
            if let Some(found) = self.named(t.get(field)) {
                return Some(found);
            }
        }
        None
    }

    pub fn retail_kind(&self, t: &Tags) -> Option<&'static str> {
        let category = t.get("amenity");
        if category == Some("fuel") {
            return Some("fuel");
        }
        if within(t.get("shop"), &self.food_shops) {
            return Some("grocery");
        }
        match self.recognized(t).as_deref() {
            Some("mcdonalds") => return Some("fast_food"),
            Some("nova_poshta") => return Some("post"),
            _ => {}
        }
        if within(category, &self.service_amenity) || within(t.get("shop"), &self.service_shops) {
            return Some("service");
        }
        None
    }

    fn brand(&self, t: &Tags) -> Option<String> {
        let category = self.retail_kind(t)?;
        let found = self.recognized(t);
        match category {
            "fuel" => found.filter(|f| self.fuel.contains(f)),
            "service" => found.filter(|f| self.networks.contains(f)),
            "grocery" => found.filter(|f| {
                !self.fuel.contains(f) && !self.networks.contains(f) && f != "mcdonalds" && f != "nova_poshta"
            }),
            _ => found,
        }
    }

    fn post_type(t: &Tags) -> &'static str {
        let vending: Vec<&str> = t.get("vending").unwrap_or("").split(';').collect();
        if is(t.get("amenity"), "parcel_locker")
            || is(t.get("man_made"), "parcel_locker")
            || is(t.get("shop"), "parcel_locker")
            || vending.iter().any(|v| matches!(*v, "parcel_pickup" | "parcel_mail_in"))
        {
            return "locker";
        }
        if is(t.get("amenity"), "post_depot") {
            return "depot";
        }
        "office"
    }

    /// retail.enriched(tags): a copy with e2r_brand and e2r_post_type of its own.
    pub fn enriched(&self, tags: &Tags) -> Tags {
        let mut result = tags.clone();
        result.remove("e2r_brand");
        result.remove("e2r_post_type");
        if let Some(b) = self.brand(&result) {
            result.set("e2r_brand", &b);
        }
        if self.retail_kind(&result) == Some("post") {
            let p = Self::post_type(&result);
            result.set("e2r_post_type", p);
        }
        result
    }

    // ---- fast_style.py / nature.py ----

    pub fn ground_kind(&self, t: &Tags) -> Option<&'static str> {
        if self.islands.iter().any(|(k, v)| t.get(k) == Some(v.as_str())) && t.get("area") != Some("no") {
            return Some("island");
        }
        let leisure = t.get("leisure");
        if leisure == Some("playground") {
            return Some("playground");
        }
        if within(leisure, &self.fields) {
            return Some(if within(t.get("surface"), &self.hard_fields) { "paved" } else { "meadow" });
        }
        if within(t.get("amenity"), &self.sites) || matches!(leisure, Some("sports_centre" | "stadium")) {
            return Some("residential");
        }
        let landuse = t.get("landuse");
        if landuse == Some("allotments") {
            return Some("orchard");
        }
        if within(landuse, &self.paved)
            || is(t.get("amenity"), "parking")
            || is(t.get("place"), "square")
            || (is(t.get("highway"), "pedestrian") && is(t.get("area"), "yes"))
        {
            return Some("paved");
        }
        if within(landuse, &self.woods) || within(t.get("natural"), &self.woods) {
            return Some("forest");
        }
        if within(leisure, &self.parks) || within(landuse, &self.parks) {
            return Some("park");
        }
        if landuse == Some("residential") {
            return Some("residential");
        }
        nature_ground_kind(t)
    }

    pub fn rail_tags(&self, t: &impl Get) -> Tags {
        Tags(self.rail_tags.iter().filter_map(|k| t.get(k).map(|v| (k.clone(), v.to_string()))).collect())
    }

    pub fn line_kind(&self, t: &impl Get) -> Option<&'static str> {
        if is(t.get("natural"), "coastline") {
            return Some("coastline");
        }
        if within(t.get("railway"), &self.rails)
            && none_or_no(t.get("tunnel"))
            && none_or_no(t.get("covered"))
            && t.get("area") != Some("yes")
        {
            return Some("rail");
        }
        if is(t.get("man_made"), "gantry") {
            return Some("gantry");
        }
        if within(t.get("highway"), &self.paths)
            && t.get("area") != Some("yes")
            && none_or_no(t.get("bridge"))
            && none_or_no(t.get("tunnel"))
            && matches!(t.get("layer").unwrap_or("0"), "0" | "")
        {
            return Some("path");
        }
        if is(t.get("natural"), "tree_row") {
            return Some("tree_row");
        }
        match t.get("barrier") {
            Some("fence" | "wall") => return Some("fence"),
            Some("guard_rail") => return Some("guard_rail"),
            Some("hedge") => return Some("hedge"),
            _ => {}
        }
        if is(t.get("power"), "minor_line") {
            return Some("power");
        }
        None
    }

    fn poi(&self, t: &Tags) -> bool {
        for key in ["shop", "office", "craft"] {
            if let Some(v) = t.get(key) {
                if !v.is_empty() && !self.poi_not.contains(v) {
                    return true;
                }
            }
        }
        within(t.get("amenity"), &self.poi_amenity)
    }

    pub fn point_kind(&self, t: &Tags) -> Option<&'static str> {
        let retail = self.retail_kind(t);
        if let Some(r) = retail {
            if !(self.pois && r == "service" && self.poi(t)) {
                return Some(r);
            }
        }
        let highway = t.get("highway");
        if is(t.get("natural"), "tree") {
            return Some("tree");
        }
        match highway {
            Some("street_lamp") => return Some("lamp"),
            Some("crossing") => {
                let marked = if t.has("crossing:markings") { t.get("crossing:markings") } else { t.get("crossing") };
                return if within(marked, &self.unmarked) { None } else { Some("crossing") };
            }
            Some("give_way") => return Some("give_way"),
            Some("stop") => return Some("stop_sign"),
            Some("mini_roundabout") => return Some("mini_roundabout"),
            Some("turning_circle" | "turning_loop") => return Some("turning_circle"),
            Some("traffic_signals") => return Some("signal"),
            Some("speed_camera") => return Some("speed_camera"),
            _ => {}
        }
        if is(t.get("railway"), "level_crossing") {
            return Some("level_crossing");
        }
        if t.get("traffic_sign").is_some_and(|v| !v.is_empty()) {
            return Some("traffic_sign");
        }
        if highway == Some("bus_stop")
            || (is(t.get("public_transport"), "platform") && ["bus", "trolleybus", "tram"].iter().any(|k| is(t.get(k), "yes")))
        {
            return Some("stop");
        }
        if within(t.get("entrance"), &self.entrances) {
            return Some("entrance");
        }
        if is(t.get("leisure"), "playground") {
            return Some("playground");
        }
        match t.get("amenity") {
            Some("bench") => return Some("bench"),
            Some("waste_basket") => return Some("waste_basket"),
            _ => {}
        }
        match t.get("barrier") {
            Some("lift_gate") => return Some("lift_gate"),
            Some("gate" | "swing_gate" | "sliding_gate" | "wicket_gate") => return Some("gate"),
            _ => {}
        }
        if self.pois && self.poi(t) {
            return Some("poi");
        }
        if self.pois && within(t.get("entrance"), &self.doors) {
            return Some("door");
        }
        None
    }
}

/// re.fullmatch(r'(?:новапошта|новаяпочта|novaposhta|novapost)(?:відділення|отделение)?(?:no)?[0-9]+', s)
fn nova_poshta_branch(s: &str) -> bool {
    for head in ["новапошта", "новаяпочта", "novaposhta", "novapost"] {
        let Some(rest) = s.strip_prefix(head) else { continue };
        for office in ["відділення", "отделение", ""] {
            let Some(rest) = rest.strip_prefix(office) else { continue };
            for no in ["no", ""] {
                let Some(rest) = rest.strip_prefix(no) else { continue };
                if !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_digit()) {
                    return true;
                }
            }
        }
    }
    false
}

/// nature.ground_kind
fn nature_ground_kind(t: &Tags) -> Option<&'static str> {
    let (land, natural) = (t.get("landuse"), t.get("natural"));
    match natural {
        Some("bare_rock") => return Some("bare_rock"),
        Some("scree") => return Some("scree"),
        Some("beach") => return Some("beach"),
        Some("wetland") => return Some("wetland"),
        Some("glacier") => return Some("glacier"),
        Some("scrub") => return Some("scrub"),
        Some("heath") => return Some("heath"),
        Some("shingle") => return Some("scree"),
        Some("sand") => return Some("beach"),
        Some("bare_ground") => return Some("bare_ground"),
        Some("grassland" | "fell") => return Some("meadow"),
        _ => {}
    }
    match land {
        Some("meadow" | "grass") => Some("meadow"),
        Some("farmyard") => Some("bare_ground"),
        Some("farmland") => Some("farmland"),
        Some("orchard") => Some("orchard"),
        Some("vineyard") => Some("vineyard"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nova_poshta_branches() {
        assert!(nova_poshta_branch("новапошта12"));
        assert!(nova_poshta_branch("новапоштавідділенняno5"));
        assert!(nova_poshta_branch("novaposhtano1"));
        assert!(!nova_poshta_branch("новапошта"));
        assert!(!nova_poshta_branch("novapostha1"));
    }
}
