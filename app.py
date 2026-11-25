import base64
import json
import os
import re
from urllib.parse import parse_qs, parse_qsl, quote, urlsplit

import pandas as pd
import streamlit as st

# Optional: streaming JSON parser. If `ijson` is in requirements.txt, big HAR files
# are processed entry-by-entry (low RAM). Without it the app falls back to json.load.
try:
    import ijson
except ImportError:  # pragma: no cover
    ijson = None

st.set_page_config(page_title="GA360 Detector", page_icon="🕵️‍♂️", layout="wide")

# ==========================================
# CONFIG (all thresholds and weights live here)
# ==========================================
APP_VERSION = "42"

LIMITS = {
    "ep_per_event": 25,     # free GA4: 25 event params / event; GA360: 100
    "value_len": 100,       # custom param value length (informational, see HARD_RULES)
    "user_props": 25,       # user properties in a single hit
    "item_custom": 27,      # item-level custom params: collection limit (applies to free GA4 as well)
    "global_ep": 50,        # unique ep.* names in the whole session (contextual rule)
}

# Rules that count as a "limit exceeded" signal in the verdict.
# r2 (value length) is informational only: Google states that 360 does not raise character limits.
# Add "r2" here if you want it back as a hard signal.
HARD_RULES = ("r1", "r3", "r4")

SCORE = {
    "sst": 10,          # first-party collection endpoint
    "multi_tag": 10,    # more than one GA4 property
    "cm360": 10,        # CM360 footprints
    "floodlight": 5,    # base Floodlight (DV360/GMP) only
    "event_max": 30,    # heaviest single hit
    "session_max": 29,  # vocabulary size across the session
}
INFRA_MAX = SCORE["sst"] + SCORE["multi_tag"] + max(SCORE["cm360"], SCORE["floodlight"])
SCORE_MAX = INFRA_MAX + SCORE["event_max"] + SCORE["session_max"]
PROBABLE_THRESHOLD = 60
INFRA_FLAG_THRESHOLD = 20

CONFIDENCE_HARD_ONE = "90%"
CONFIDENCE_HARD_MULTI = "95%"

GOOGLE_HOSTS = (
    "google-analytics.com", "analytics.google.com", "googletagmanager.com",
    "doubleclick.net", "googleadservices.com", "googlesyndication.com",
)
STATIC_EXT = (".js", ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg", ".jpeg",
              ".svg", ".gif", ".webp", ".ico", ".map")
NATIVE_EXCLUDES = {
    "page_title", "page_location", "page_referrer", "page_path", "search_term",
    "content_group", "campaign", "source", "medium", "term", "content",
}
STANDARD_MP_ITEM_SUFFIXES = {
    "item_id", "item_name", "item_brand", "item_category", "item_category2",
    "item_category3", "item_category4", "item_category5", "price", "quantity",
    "item_variant", "promotion_name", "promotion_id", "coupon", "discount",
    "index", "affiliation", "item_list_name", "item_list_id",
}

# Matched on hostname (suffix) or on URL path (regex) - never on the whole URL string.
ALT_SYSTEMS = {
    "Adobe Analytics (Enterprise)": {"hosts": ("omtrdc.net", "adobedc.net", "2o7.net"), "paths": (r"/b/ss/",)},
    "Piwik PRO": {"hosts": ("piwik.pro",), "paths": (r"/ppms\.(php|js)$",)},
    "Matomo": {"hosts": ("matomo.cloud",), "paths": (r"/(matomo|piwik)\.(php|js)$",)},
    "Amplitude": {"hosts": ("amplitude.com",), "paths": ()},
    "Mixpanel": {"hosts": ("mixpanel.com",), "paths": ()},
    "Hotjar": {"hosts": ("hotjar.com", "hotjar.io"), "paths": ()},
    "Snowplow": {"hosts": (), "paths": (r"/com\.snowplowanalytics\.snowplow/tp2",)},
    "Segment": {"hosts": ("segment.io", "segment.com"), "paths": ()},
    "Heap": {"hosts": ("heapanalytics.com",), "paths": ()},
    "Contentsquare": {"hosts": ("contentsquare.net", "contentsquare.com"), "paths": ()},
    "Fullstory": {"hosts": ("fullstory.com",), "paths": ()},
    "Microsoft Clarity": {"hosts": ("clarity.ms",), "paths": ()},
    "PostHog": {"hosts": ("posthog.com",), "paths": ()},
    "Tealium": {"hosts": ("tiqcdn.com", "tealiumiq.com"), "paths": ()},
    "Yandex Metrica": {"hosts": ("mc.yandex.ru", "mc.yandex.com"), "paths": ()},
}

# rule id -> prefix of the keys in the dictionary below
RULE_KEYS = {
    "r1": "rule_t1", "r2": "rule_t2", "r3": "rule_t3", "r4": "rule_t4",
    "r5": "rule_m5", "r6": "rule_m6", "r7": "rule_m7", "r8": "rule_m8", "r9": "rule_m9",
}

# ==========================================
# DICTIONARY (ENGLISH ONLY)
# ==========================================
t = {
    "sidebar_mode": "**Operation Mode: Bulk HAR Analysis (Upload)**",
    "sidebar_version": f"Version: {APP_VERSION}",
    "sidebar_changelog": """
**🔄 What's new in version 42?**
* **Verdict logic aligned with Google's docs:** limits re-checked; item-level rule now uses the 27 collection limit; value length is informational only.
* **Softer wording:** a network hit shows what the site *sent*, not what GA *accepted*, so limit violations are a *strong signal* (90–95%), not 100% proof.
* **Evidence:** every rule shows the hit and parameters that triggered it.
* **Fewer false positives:** stricter request filter, server-side detection based on GA4 hits only, host-based competitor matching.
* **Result persistence:** results survive downloads/reruns.
""",
    "title": "GA360 Detector",
    "tabs": ["🚀 Scan Panel", "📚 Knowledge Base (EDU)", "📥 .HAR File Guide"],
    "upload_desc": "Export `.har` files from your browser and upload them below. **You can drag and drop multiple files at once.**",
    "upload_warning": "⚠️ **Pro-tip:** To prevent server timeouts, ensure your `.har` files are under 200MB. Check the instruction tab to learn how to generate lightweight logs.",
    "privacy_note": "🔒 Files are processed in memory and are not stored by the app. HAR files can contain cookies and personal data - upload only files you are allowed to share.",
    "btn_clear_files": "🗑️ Clear uploaded files",
    "upload_label": "Choose .har files",
    "btn_analyze": "🔍 Analyze Uploaded Files",
    "spinner_msg": "Analyzing file: {}...",
    "expander_title": "{} - Analysis Result (File: {})",
    "err_no_scripts": "No analytics scripts or footprints were found in this HAR file. Ensure the file was recorded correctly.",
    "err_read_file": "Error reading file {}: {}",
    "warn_no_files": "Please upload at least one .har file first.",
    "table_detailed_title": "📊 Detailed Analysis Report (Bulk Export)",
    "chk_legend": "Include 'RULE DESCRIPTION' row in the export",
    "btn_download_csv_detailed": "📥 Download CSV Report",
    "expander_copy": "📋 1-Click Copy to Clipboard (Paste directly to Excel/Google Sheets)",
    "csv_filename_detailed": "Report_GA360_Detector.csv",
    "csv_err_msg": "No network events.",
    "csv_col_domain": "Domain (from file)",
    "csv_col_verdict": "Final Verdict",
    "csv_col_confidence": "Verdict Confidence",
    "csv_col_tid": "Property ID (TID)",
    "csv_col_other": "Other Analytics System",
    "csv_col_reason": "Key Rationale",
    "csv_col_evidence": "Evidence (key hits)",
    "md_domain": "DOMAIN / WEBSITE",
    "md_verdict": "VERDICT",
    "md_confidence": "VERDICT CONFIDENCE",
    "md_other": "OTHER ANALYTICS SYSTEM",
    "md_tids": "Detected Measurement IDs (tid)",
    "md_rules_title": "📋 Rule Validation Summary",
    "md_evidence_title": "🔎 Evidence (what triggered each rule)",
    "table_header_status": "Status",
    "table_header_type": "Rule Type",
    "table_header_rule": "Validation Rule / Limit",
    "table_header_result": "Network Analysis Result",
    "rule_t1_type": "Hard rule #1 (Event Limit)",
    "rule_t1_desc": "Custom event parameters (ep.*/epn.*) in a single hit > 25",
    "rule_t1_res": "Max detected: {}",
    "rule_t2_type": "Indicator #2 (Size Limit)",
    "rule_t2_desc": "Custom parameter value length > 100 characters (informational, not scored)",
    "rule_t2_res": "Longest custom value: {} chars",
    "rule_t3_type": "Hard rule #3 (User Limit)",
    "rule_t3_desc": "User properties (up.*/upn.*) in a single hit > 25",
    "rule_t3_res": "Max detected: {}",
    "rule_t4_type": "Hard rule #4 (Product Limit)",
    "rule_t4_desc": "Custom item-level parameters per product > 27 (collection limit)",
    "rule_t4_res": "Max detected: {} in a single product",
    "rule_m5_type": "Contextual rule #1 (Data Density)",
    "rule_m5_desc": "Total unique ep.* parameters in session > 50",
    "rule_m5_res": "Total detected: {} unique",
    "rule_m6_type": "Contextual rule #2 (IT Architecture)",
    "rule_m6_desc": "Server-Side Tagging (GA4 hits sent to a 1st-party domain)",
    "rule_m6_res": "Collection endpoint detected: {}",
    "rule_m7_type": "Contextual rule #3 (Governance)",
    "rule_m7_desc": "Corporate Multi-tagging setup (more than one GA4 property)",
    "rule_m7_res_yes": "Yes ({})",
    "rule_m7_res_no": "No",
    "rule_m8_type": "Contextual rule #4 (Ad Server)",
    "rule_m8_desc": "CM360 specific parameters & paths",
    "rule_m9_type": "Contextual rule #5 (DSP)",
    "rule_m9_desc": "Base Floodlight tags (DV360/GMP)",
    "rule_m9_res_yes": "Yes",
    "rule_m9_res_no": "No",
    "verdict_no_ga": "No Google Analytics",
    "verdict_ua": "Legacy Universal Analytics (no GA4)",
    "verdict_tag_only": "GA4 tag loaded, no hits captured (consent not granted?)",
    "verdict_ga360": "GA 360 (strong signal)",
    "verdict_prob_ga360": "Probably GA 360",
    "verdict_free_infra": "Free GA4 (Advanced Infrastructure)",
    "verdict_free_empty": "Free GA4 (Empty Parameters)",
    "verdict_free": "Free GA4",
    "reason_no_ga": "No Google traffic detected. Classification based on competitor market footprints.",
    "reason_ua": "Only Universal Analytics hits (UA-*, /j/collect) were found. UA stopped processing data in 2023/2024.",
    "reason_tag_only": "A gtag.js loader for a GA4 property was requested, but no GA4 collect hits were recorded. Re-record the HAR after accepting all cookies.",
    "reason_hard": "Limit(s) exceeded in the network hits: {}. The site sent more than free GA4 accepts - a strong signal, but not proof (GA drops the excess server-side).",
    "reason_pts": "Analysis Score: {}/{} pts (Infra: {}/{} pts, Data_Event: {}/{} pts, Data_Session: {}/{} pts)",
    "reason_events": "Based on {} GA4 events.",
    "reason_low_sample": "⚠️ Low sample - record a longer session (product page, cart, checkout) for a reliable verdict.",
    "har_title": "📥 Guide to Generating Actionable (and Lightweight) .HAR Files",
    "har_subtitle": "Follow this procedure to generate network logs that are rich in analytics data but small enough to avoid server timeout crashes.",
}

# --- WIDGET / RESULT STATE ---
st.session_state.setdefault("uploader_key", 0)
st.session_state.setdefault("results", [])

# --- SIDEBAR ---
logo_path = "FSE_Logo.png"
if os.path.exists(logo_path):
    st.sidebar.image(logo_path)
else:
    st.sidebar.markdown("<h3 style='text-align: center; color: #888;'>[ LOGO ]</h3>", unsafe_allow_html=True)

st.sidebar.write("")
st.sidebar.markdown(t["sidebar_mode"])
st.sidebar.caption(t["sidebar_version"])
st.sidebar.info(t["sidebar_changelog"])
st.sidebar.markdown(
    """
    <div style="margin-top: 50px; text-align: center; color: #888;">
        <small>© Full Stack Experts 2026</small>
    </div>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# HELPERS
# ==========================================
def host_in(host, suffixes):
    """True if host equals one of the suffixes or is its subdomain."""
    return any(host == s or host.endswith("." + s) for s in suffixes)


GA4_ID_RE = re.compile(r"G-[A-Z0-9]{6,12}")
LOW_SAMPLE_EVENTS = 10  # fewer GA4 events than this -> verdict is weakly supported

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def registrable(host):
    """Approximate registrable domain (no tldextract dependency)."""
    if not host or _IP_RE.match(host):
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def short(items, n=12):
    items = list(items)
    txt = ", ".join(items[:n])
    return txt + (f", … (+{len(items) - n})" if len(items) > n else "")


def md_safe(text):
    return str(text).replace("`", "'").replace("|", "/")


def post_text_of(post_data):
    text = post_data.get("text", "") or ""
    if post_data.get("encoding") == "base64" and text:
        try:
            text = base64.b64decode(text).decode("utf-8")
        except Exception:
            pass
    if not text and post_data.get("params"):
        text = "&".join(f"{quote(p.get('name', ''))}={quote(p.get('value', '') or '')}" for p in post_data["params"])
    return text


def parse_body_line(line):
    try:
        parsed = parse_qs(line, keep_blank_values=False)
        if parsed:
            return {k: v[0] for k, v in parsed.items() if v}
    except Exception:
        pass
    return {m[0]: m[1] for m in re.findall(r"([a-zA-Z0-9_\.\-]+)=([^&\s;]+)", line)}


# ==========================================
# ENGINE: streaming analyzer (one HAR entry at a time)
# ==========================================
class HarAnalyzer:
    def __init__(self):
        self.page_host = None      # host from log.pages[0].title (when it is a URL)
        self.doc_host = None       # host of the first text/html response
        self.first_host = None
        self.relevant_hits = 0
        self.alt_systems = set()
        self.ga4_containers = set()
        self.ga4_tids = set()
        self.malformed_tids = set()
        self.ga4_events = 0
        self.ua_seen = False
        self.ga4_hit_hosts = {}    # host -> example "host/path"
        self.global_ep = set()
        self.best = {}             # rule id -> (value, evidence text)
        self.cm360_flags = {}      # "/ddm/" | "cost" | "qty" | "dclid" -> example label
        self.floodlight_example = None

    # ---- public ----
    def set_page_title(self, title):
        if isinstance(title, str) and title.startswith("http"):
            self.page_host = (urlsplit(title).hostname or "").lower() or None

    def feed(self, entry):
        req = entry.get("request") or {}
        url = req.get("url") or ""
        if not url:
            return
        parts = urlsplit(url)  # urlsplit (not urlparse) keeps ;matrix params in path
        host = (parts.hostname or "").lower()
        path = parts.path.lower()
        url_lower = url.lower()

        if self.first_host is None:
            self.first_host = host
        if self.doc_host is None:
            mime = ((entry.get("response") or {}).get("content") or {}).get("mimeType") or ""
            if mime.startswith("text/html"):
                self.doc_host = host

        self._detect_alt(host, path)

        params = {q["name"]: (q.get("value") or "") for q in (req.get("queryString") or []) if q.get("name")}
        if not params and parts.query:
            params = dict(parse_qsl(parts.query, keep_blank_values=True))

        # gtag.js loader -> tells us a GA4 property exists even if no hits were sent
        if host_in(host, ("googletagmanager.com",)) and path == "/gtag/js":
            cid = str(params.get("id", "")).upper()
            if cid.startswith("G-"):
                self.ga4_containers.add(cid)

        if path.endswith(STATIC_EXT) and "dcmads.js" not in url_lower:
            return

        # cheap relevance checks first; only then look into POST bodies
        cheap = (host_in(host, GOOGLE_HOSTS) or path.endswith("/collect")
                 or any(k in params for k in ("tid", "dclid", "gcs")))
        post_text = ""
        if cheap:
            post_text = post_text_of(req.get("postData") or {})
        else:
            if (req.get("method") or "").upper() != "POST":
                return
            post_text = post_text_of(req.get("postData") or {})
            if "tid=" not in post_text:
                return

        events = [{**params, **parse_body_line(line.strip())} for line in post_text.splitlines() if line.strip()]
        if not events:
            events = [params]

        self.relevant_hits += 1
        label = f"{host}{parts.path}"[:90]
        self._request_level(host, path, url_lower, params, label)

        for e in events:
            if "dclid=" in str(e.get("dl", "")).lower():
                self._cm360("dclid", label)
            tid = str(e.get("tid") or "").upper()
            is_ua = (tid.startswith("UA-") or path.endswith("/j/collect")
                     or (path.endswith("/collect") and str(e.get("v")) == "1" and not tid.startswith("G-")))
            if is_ua:
                self.ua_seen = True
                continue
            if not tid.startswith("G-"):
                continue
            if GA4_ID_RE.fullmatch(tid):
                self.ga4_tids.add(tid)
            else:
                # Placeholder ID (e.g. "G-111") - common when the web tag sends to a server-side GTM
                # container that fills in the real ID. The hit is real (it counts for SST and for the
                # event analysis), but it is not a distinct property, so it is kept out of multi-tagging.
                self.malformed_tids.add(tid)
            if path.startswith("/measurement/"):
                continue  # Google Ads conversion mirror pings, not GA4 collect hits
            self.ga4_events += 1
            self.ga4_hit_hosts.setdefault(host, label)
            self._ga4_event(e, label)

    # ---- internals ----
    def _detect_alt(self, host, path):
        for name, cfg in ALT_SYSTEMS.items():
            if host_in(host, cfg["hosts"]) or any(re.search(p, path) for p in cfg["paths"]):
                self.alt_systems.add(name)

    def _cm360(self, flag, label):
        self.cm360_flags.setdefault(flag, label)

    def _request_level(self, host, path, url_lower, params, label):
        if any(k.lower() == "dclid" for k in params):
            self._cm360("dclid", label)
        if "dcmads.js" in url_lower:
            self._cm360("/ddm/", label)
        if not host_in(host, ("doubleclick.net",)):
            return
        # Floodlight puts its params in the PATH as matrix params (;qty=1;cost=9.99;dc_pre=1), not in the query
        keys = set(re.findall(r"[;/]([a-z0-9_]+)=", path)) | {k.lower() for k in params}
        # gtag-based Floodlight: ad.doubleclick.net/activity;src=...  | legacy tag: fls.doubleclick.net/activityi;src=...
        if (host.startswith("fls.") or path.startswith("/activity") or "/ddm/activity" in path
                or "dc_pre" in keys):
            self.floodlight_example = self.floodlight_example or label
        if "/ddm/" in path:
            self._cm360("/ddm/", label)
        for k in ("cost", "qty"):
            if k in keys:
                self._cm360(k, label)

    def _record(self, rule, value, text_fn):
        if value > self.best.get(rule, (0, ""))[0]:
            self.best[rule] = (value, text_fn())

    def _ga4_event(self, e, label):
        en = e.get("en") or "?"
        ep_keys = [k for k in e if k.startswith(("ep.", "epn."))]
        up_keys = [k for k in e if k.startswith(("up.", "upn."))]
        names = [k.split(".", 1)[1] for k in ep_keys]
        self.global_ep.update(names)

        self._record("r1", len(ep_keys), lambda: f"`{md_safe(en)}` @ {md_safe(label)} · {len(ep_keys)} custom params: {md_safe(short(names))}")
        self._record("r3", len(up_keys), lambda: f"`{md_safe(en)}` @ {md_safe(label)} · {len(up_keys)} user properties: {md_safe(short(k.split('.', 1)[1] for k in up_keys))}")

        for k in ep_keys:
            if k.split(".", 1)[1] in NATIVE_EXCLUDES:
                continue
            n = len(str(e[k]))
            self._record("r2", n, lambda k=k, n=n: f"`{md_safe(en)}` @ {md_safe(label)} · `{md_safe(k)}` = {n} chars")

        # Item-level custom params.
        # gtag format: pr1=idSKU~nmName~brBrand~...~k0item_color~v0red  (kN = custom key, vN = custom value)
        # Measurement-Protocol-like flattened format: items.0.custom_name=...
        mp_items = {}
        for k, v in e.items():
            if re.fullmatch(r"(?:pr|pi)\d+", k):
                keys = [tok for tok in str(v).split("~") if re.match(r"k\d+", tok)]
                self._record("r4", len(keys), lambda k=k, keys=keys: f"`{md_safe(en)}` @ {md_safe(label)} · product `{k}`: {len(keys)} custom item params ({md_safe(short((x[2:] for x in keys), 6))})")
                continue
            m = re.match(r"^items\.(\d+)\.(.+)", k)
            if m and m.group(2) not in STANDARD_MP_ITEM_SUFFIXES:
                mp_items.setdefault(m.group(1), set()).add(m.group(2))
        for idx, custom in mp_items.items():
            self._record("r4", len(custom), lambda idx=idx, custom=custom: f"`{md_safe(en)}` @ {md_safe(label)} · item {idx}: {len(custom)} custom item params ({md_safe(short(sorted(custom), 6))})")

    # ---- verdict ----
    def finalize(self, fallback_name, t_dict):
        domain = self.page_host.removeprefix("www.") if self.page_host else fallback_name
        site_host = self.page_host or self.doc_host or self.first_host

        if self.relevant_hits == 0 and not self.alt_systems and not self.ga4_containers:
            return {"status": "empty", "domain": domain}

        site_reg = registrable(site_host) if site_host else None
        sst_hosts = sorted(h for h in self.ga4_hit_hosts
                           if site_reg and registrable(h) == site_reg and not host_in(h, GOOGLE_HOSTS))

        v = {rid: self.best.get(rid, (0, ""))[0] for rid in ("r1", "r2", "r3", "r4")}
        ev = {rid: self.best.get(rid, (0, ""))[1] for rid in ("r1", "r2", "r3", "r4")}
        n_global = len(self.global_ep)
        n_tids = len(self.ga4_tids)

        flags = {
            "r1": v["r1"] > LIMITS["ep_per_event"],
            "r2": v["r2"] > LIMITS["value_len"],
            "r3": v["r3"] > LIMITS["user_props"],
            "r4": v["r4"] > LIMITS["item_custom"],
            "r5": n_global > LIMITS["global_ep"],
            "r6": bool(sst_hosts),
            "r7": n_tids > 1,
            "r8": bool(self.cm360_flags),
            "r9": bool(self.floodlight_example),
        }

        cm_txt = ", ".join(f"{k}: {'Yes' if k in self.cm360_flags else 'No'}" for k in ("/ddm/", "cost", "qty", "dclid"))
        results = {
            "r1": t_dict["rule_t1_res"].format(v["r1"]),
            "r2": t_dict["rule_t2_res"].format(v["r2"]),
            "r3": t_dict["rule_t3_res"].format(v["r3"]),
            "r4": t_dict["rule_t4_res"].format(v["r4"]),
            "r5": t_dict["rule_m5_res"].format(n_global),
            "r6": t_dict["rule_m6_res"].format(", ".join(sst_hosts[:3]) if sst_hosts else "No"),
            "r7": t_dict["rule_m7_res_yes"].format(n_tids) if flags["r7"] else t_dict["rule_m7_res_no"],
            "r8": cm_txt,
            "r9": t_dict["rule_m9_res_yes"] if flags["r9"] else t_dict["rule_m9_res_no"],
        }
        ev["r5"] = f"{n_global} unique ep.* names: {md_safe(short(sorted(self.global_ep), 15))}" if n_global else ""
        ev["r6"] = f"first GA4 hit on 1st-party host: {md_safe(self.ga4_hit_hosts[sst_hosts[0]])}" if sst_hosts else ""
        ev["r7"] = f"{md_safe(', '.join(sorted(self.ga4_tids)))}" if flags["r7"] else ""
        ev["r8"] = "; ".join(f"{k} → {md_safe(lbl)}" for k, lbl in self.cm360_flags.items())
        ev["r9"] = md_safe(self.floodlight_example) if self.floodlight_example else ""

        # --- scoring ---
        infra = 0
        if flags["r6"]:
            infra += SCORE["sst"]
        if flags["r7"]:
            infra += SCORE["multi_tag"]
        if flags["r8"]:
            infra += SCORE["cm360"]
        elif flags["r9"]:
            infra += SCORE["floodlight"]
        data_ev = int(min(v["r1"] / LIMITS["ep_per_event"] * SCORE["event_max"], SCORE["event_max"]))
        data_gl = int(min(n_global / LIMITS["global_ep"] * SCORE["session_max"], SCORE["session_max"]))
        total = infra + data_ev + data_gl

        hard_hits = [rid for rid in HARD_RULES if flags[rid]]
        empty_ga4 = (v["r1"] == 0 and v["r4"] == 0 and n_global == 0)
        other_txt = f"Yes, {', '.join(sorted(self.alt_systems))}" if self.alt_systems else "No"

        if not self.ga4_tids and not self.ga4_events:
            if self.ua_seen:
                verdict, conf, reason = t_dict["verdict_ua"], "90%", t_dict["reason_ua"]
            elif self.ga4_containers:
                verdict, conf, reason = t_dict["verdict_tag_only"], "N/A", t_dict["reason_tag_only"]
            else:
                verdict, reason = t_dict["verdict_no_ga"], t_dict["reason_no_ga"]
                if "Adobe Analytics (Enterprise)" in self.alt_systems:
                    conf = "95%"
                elif self.alt_systems:
                    conf = "90%"
                else:
                    conf = "80%"
        else:
            reason = t_dict["reason_pts"].format(total, SCORE_MAX, infra, INFRA_MAX, data_ev, SCORE["event_max"], data_gl, SCORE["session_max"])
            reason += " " + t_dict["reason_events"].format(self.ga4_events)
            if self.ga4_events < LOW_SAMPLE_EVENTS:
                reason += " " + t_dict["reason_low_sample"]
            if hard_hits:
                verdict = t_dict["verdict_ga360"]
                conf = CONFIDENCE_HARD_MULTI if len(hard_hits) > 1 else CONFIDENCE_HARD_ONE
                reason = t_dict["reason_hard"].format(", ".join(h.upper() for h in hard_hits)) + " " + reason
            elif total >= PROBABLE_THRESHOLD:
                verdict, conf = t_dict["verdict_prob_ga360"], f"{total}%"
            elif infra >= INFRA_FLAG_THRESHOLD:
                verdict, conf = t_dict["verdict_free_infra"], f"{100 - total}%"
            elif empty_ga4:
                verdict, conf = t_dict["verdict_free_empty"], "95%"
            else:
                verdict, conf = t_dict["verdict_free"], f"{100 - total}%"

        if self.ga4_tids:
            tid_txt = ", ".join(sorted(self.ga4_tids))
            if self.malformed_tids:
                tid_txt += f" (+ placeholder: {', '.join(sorted(self.malformed_tids))})"
        elif self.malformed_tids:
            tid_txt = f"placeholder only: {', '.join(sorted(self.malformed_tids))}"
        elif self.ga4_containers:
            tid_txt = ", ".join(sorted(self.ga4_containers)) + " (tag only)"
        else:
            tid_txt = t_dict["verdict_no_ga"]

        rules = []
        for rid, key in RULE_KEYS.items():
            rules.append({
                "id": rid,
                "type": t_dict[f"{key}_type"],
                "desc": t_dict[f"{key}_desc"],
                "flag": flags[rid],
                "result": results[rid],
                "evidence": ev.get(rid, ""),
            })

        return {"status": "ok", "domain": domain, "verdict": verdict, "confidence": conf,
                "tids": tid_txt, "other": other_txt, "reason": reason, "rules": rules}


def read_har(uploaded_file):
    """Feed every HAR entry into a HarAnalyzer. Streams with ijson when available."""
    if ijson is not None:
        try:
            analyzer = HarAnalyzer()
            uploaded_file.seek(0)
            for page in ijson.items(uploaded_file, "log.pages.item"):
                analyzer.set_page_title(page.get("title", ""))
                break
            uploaded_file.seek(0)
            for entry in ijson.items(uploaded_file, "log.entries.item"):
                analyzer.feed(entry)
            return analyzer
        except Exception:
            pass  # fall back to the plain json parser below

    uploaded_file.seek(0)
    har = json.load(uploaded_file)
    log = har.get("log", {}) if isinstance(har, dict) else {}
    analyzer = HarAnalyzer()
    pages = log.get("pages") or []
    if pages:
        analyzer.set_page_title(pages[0].get("title", ""))
    for entry in log.get("entries", []):
        analyzer.feed(entry)
    del har, log
    return analyzer


def analyze_uploaded_file(f):
    fallback = re.sub(r"\.har$", "", f.name, flags=re.IGNORECASE)
    try:
        analyzer = read_har(f)
        res = analyzer.finalize(fallback, t)
    except Exception as exc:
        return {"status": "error", "file": f.name, "domain": fallback, "error": str(exc)}
    res["file"] = f.name
    return res


# ==========================================
# RENDERING / EXPORT
# ==========================================
def result_to_row(res):
    """Flat dict for the CSV/TSV export."""
    row = {
        t["csv_col_domain"]: res["domain"],
        t["csv_col_verdict"]: "Error" if res["status"] != "ok" else res["verdict"],
        t["csv_col_confidence"]: "0%" if res["status"] != "ok" else res["confidence"],
        t["csv_col_other"]: "No" if res["status"] != "ok" else res["other"],
        t["csv_col_tid"]: "None" if res["status"] != "ok" else res["tids"],
        t["csv_col_reason"]: (t["csv_err_msg"] if res["status"] == "empty" else res.get("error", "")) if res["status"] != "ok" else res["reason"],
    }
    for rid, key in RULE_KEYS.items():
        row[t[f"{key}_type"]] = "-"
    row[t["csv_col_evidence"]] = "-"
    if res["status"] == "ok":
        for r in res["rules"]:
            row[r["type"]] = f"{'[✅]' if r['flag'] else '[❌]'} {r['result']}"
        evidence = [f"{r['id'].upper()}: {r['evidence']}".replace("`", "") for r in res["rules"] if r["evidence"]]
        row[t["csv_col_evidence"]] = " | ".join(evidence) or "-"
    return row


def render_result(res):
    if res["status"] == "empty":
        st.warning(t["err_no_scripts"])
        return
    if res["status"] == "error":
        st.error(t["err_read_file"].format(res["file"], res.get("error", "")))
        return

    icon = lambda flag: "✅" if flag else "❌"
    lines = [
        f"* **{t['md_domain']}:** `{md_safe(res['domain'])}`",
        f"* **{t['md_verdict']}:** **{res['verdict']}**",
        f"* **{t['md_confidence']}:** `{res['confidence']}`",
        f"* **{t['md_other']}:** `{md_safe(res['other'])}`",
        f"* **{t['md_tids']}:** `{md_safe(res['tids'])}`",
        "",
        "---",
        f"### {t['md_rules_title']}",
        "",
        f"| {t['table_header_status']} | {t['table_header_type']} | {t['table_header_rule']} | {t['table_header_result']} |",
        "| :---: | :--- | :--- | :--- |",
    ]
    for r in res["rules"]:
        lines.append(f"| {icon(r['flag'])} | {r['type']} | {r['desc']} | {md_safe(r['result'])} |")
    st.markdown("\n".join(lines))
    st.caption(res["reason"])

    evidence = [r for r in res["rules"] if r["evidence"]]
    if evidence:
        st.markdown(f"**{t['md_evidence_title']}**")
        st.markdown("\n".join(f"* {icon(r['flag'])} **{r['type']}:** {r['evidence']}" for r in evidence))


# ==========================================
# UI
# ==========================================
st.title(f"🕵️‍♂️ {t['title']}")
tab1, tab2, tab3 = st.tabs(t["tabs"])

with tab1:
    col_desc, col_clear = st.columns([4, 1])
    with col_desc:
        st.markdown(t["upload_desc"])
        st.caption(t["upload_warning"])
        st.caption(t["privacy_note"])
    with col_clear:
        if st.button(t["btn_clear_files"]):
            st.session_state.uploader_key = (st.session_state.uploader_key + 1) % 100
            st.session_state.results = []
            st.rerun()

    uploaded_files = st.file_uploader(
        t["upload_label"], type=["har"], accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if st.button(t["btn_analyze"]):
        if not uploaded_files:
            st.warning(t["warn_no_files"])
        else:
            results = []
            progress = st.progress(0.0)
            for i, f in enumerate(uploaded_files):
                with st.spinner(t["spinner_msg"].format(f.name)):
                    results.append(analyze_uploaded_file(f))
                progress.progress((i + 1) / len(uploaded_files))
            progress.empty()
            st.session_state.results = results  # persisted -> survives reruns (e.g. download clicks)

    results = st.session_state.results
    if results:
        for res in results:
            with st.expander(t["expander_title"].format(res["domain"], res["file"]), expanded=False):
                render_result(res)

        st.write("---")
        st.subheader(t["table_detailed_title"])

        rows = sorted((result_to_row(r) for r in results), key=lambda x: str(x[t["csv_col_domain"]]).lower())
        include_legend = st.checkbox(t["chk_legend"], value=True)
        if include_legend:
            desc_row = {col: "-" for col in rows[0]}
            desc_row[t["csv_col_domain"]] = "ℹ️ RULE DESCRIPTION"
            for rid, key in RULE_KEYS.items():
                desc_row[t[f"{key}_type"]] = t[f"{key}_desc"]
            rows = [desc_row] + rows

        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch")

        # BOM so that Excel opens UTF-8 correctly
        csv_bytes = ("\ufeff" + df.to_csv(index=False, sep=";")).encode("utf-8")
        st.download_button(
            label=t["btn_download_csv_detailed"],
            data=csv_bytes,
            file_name=t["csv_filename_detailed"],
            mime="text/csv",
            on_click="ignore",  # no rerun on click
        )
        with st.expander(t["expander_copy"]):
            st.code(df.to_csv(index=False, sep="\t"), language="text")

with tab2:
    st.title("📚 Analytics & Business Knowledge Base")
    st.markdown("Logical documentation of the rules embedded directly within the detective's verification engine.")

    st.info(
        "**Important caveat.** A `.har` file shows what the website *sent*, not what Google Analytics *accepted*. "
        "Free GA4 silently drops or truncates anything above its limits on the server side, so a site on a free property "
        "can still *send* more than the limit. Exceeding a limit is therefore a **strong signal** (90-95% confidence), not 100% proof."
    )

    st.subheader("🔴 Limit-based Rules (strong signals)")
    with st.expander("Hard rule #1: Number of custom parameters in an event (>25)"):
        st.markdown("* **Technical Background:** Free GA4 allows **25 event parameters per event**; **GA360 allows 100**.\n* **Detection Logic:** The engine counts unique `ep.*` / `epn.*` parameters in a single GA4 hit. This is the most reliable of the limit-based rules.")
    with st.expander("Indicator #2: Maximum parameter value length (>100 characters) - informational"):
        st.markdown("* **Technical Background:** Standard GA4 truncates parameter values at **100 characters**. Google's collection-limits page states that GA360 raises some limits but **not event/parameter character limits**, so this check cannot separate 360 from free.\n* **Detection Logic:** The engine records the longest custom value (native parameters such as `page_title` are excluded). It is shown for context and **not used in the verdict** (see `HARD_RULES` in the code).")
    with st.expander("Hard rule #3: Number of User Properties in a hit (>25)"):
        st.markdown("* **Technical Background:** Google's documentation is not fully consistent here: one table lists 25 vs **100 user-scoped custom dimensions per property** for 360, while another lists **25 user properties per event** for both tiers. The 100 figure concerns *registered* dimensions, which cannot be seen in network traffic.\n* **Detection Logic:** The engine counts `up.*` / `upn.*` parameters in one hit. Treat a positive result with caution.")
    with st.expander("Hard rule #4: Custom item-level parameters per product (>27)"):
        st.markdown("* **Technical Background:** GA4 accepts up to **27 item-level custom parameters** per ecommerce event on *every* property (collection limit). Separately, the number of *registered* item-scoped custom dimensions is **10 in free GA4 and 25 in GA360**, but registration is not visible in the network.\n* **Detection Logic:** In the `gtag` format a product is a `pr1=idSKU~nm...~k0name~v0value` string; each `kN` token is one custom item parameter. Flat `items.N.*` parameters are handled with a whitelist of standard fields. The rule fires above 27 in a single product.")

    st.write("")
    st.subheader("🟡 Dynamic Contextual Scoring (Data Density Analysis)")
    with st.expander("How to read Confidence vs Score Points? (Decoding Manual)"):
        st.markdown(
            f"The score is a **heuristic**, not a probability. Maximum **{SCORE_MAX} pts**:\n\n"
            f"* **Infra (max {INFRA_MAX} pts):** {SCORE['sst']} pts for first-party (server-side) GA4 endpoint, {SCORE['multi_tag']} pts for more than one GA4 property, "
            f"{SCORE['cm360']} pts for Campaign Manager 360 footprints (or {SCORE['floodlight']} pts for base Floodlight only).\n"
            f"* **Data_Event (max {SCORE['event_max']} pts):** weight of the single heaviest GA4 hit (number of custom event parameters).\n"
            f"* **Data_Session (max {SCORE['session_max']} pts):** vocabulary size - unique `ep.*` names across the session (full marks at 50).\n\n"
            f"A score of {PROBABLE_THRESHOLD}+ gives *Probably GA 360*. Big advertisers on free GA4 can also have advanced infrastructure, so infra points alone never reach that threshold."
        )
    with st.expander("Server-Side Tagging detection"):
        st.markdown("* **Rule:** a **GA4 hit** (`tid=G-…`) sent to a host that shares the registrable domain with the analysed website (e.g. `metrics.example.com` for `www.example.com`).\n* **Why not any first-party request?** Ordinary first-party calls (`/api/data`, `/static/…`) are not tracking endpoints. Only real GA4 hits count.\n* **Limitations:** the registrable domain is approximated without a public-suffix list; SST on a completely different domain is not detected.")
    with st.expander("Ad Server Detection: Campaign Manager 360 vs DV360"):
        st.markdown("* **Footprint 1 (Click Identifier):** a `dclid` parameter (also inside the landing-page URL `dl=`).\n* **Footprint 2 (DDM Paths):** `/ddm/` paths on DoubleClick hosts and `dcmads.js`.\n* **Footprint 3 (Floodlight e-commerce parameters):** `cost` and `qty` - in Floodlight URLs they live in the **path** as matrix parameters (`;qty=1;cost=9.99`). Floodlight is shared by CM360 and DV360, so this footprint is a hint, not proof of CM360.\n* **Business Impact:** signals large media budgets, but its correlation with a GA360 licence is weak, hence the moderate weight.")
    st.markdown(
        "**Sources (Google Analytics Help):** "
        "[Event collection limits](https://support.google.com/analytics/answer/9267744) · "
        "[GA4 360](https://support.google.com/analytics/answer/11202874) · "
        "[Custom dimensions and metrics](https://support.google.com/analytics/answer/9269570)"
    )

with tab3:
    st.title(t["har_title"])
    st.markdown(t["har_subtitle"])

    st.markdown("""
    ### 🛠️ Step-by-Step Instructions for Consultants and Sales Teams:

    #### 0️⃣ Step 0: Keep the file small - but don't filter out beacons and pixels
    * Unfiltered `.har` files from e-commerce sites can exceed 300MB, which crashes the upload (`ClientDisconnect`).
    * ⚠️ **Do not** limit the view to `Fetch/XHR` and **do not** block `Img`. GA4 often sends hits as beacons (shown under **Other/ping**) or image pixels, and Floodlight/CM360 tags are typically image requests. Filtering them out hides exactly what this tool looks for.
    * Instead: clear the log before you start (🚫 icon), record only the session you need, and – if the file is still too large – hide only heavy types such as `Media` and `Font`. Whether the export respects the active filter depends on your Chrome version, so check the file size after exporting.

    #### 1️⃣ Step 1: Prepare a Clean Environment (Incognito Mode)
    * Always open the target website in a **new Incognito Window** (`Ctrl+Shift+N` or `Cmd+Shift+N`).
    * *Why?* This bypasses all cached cookies, forcing the website to re-display the privacy banner and execute all tracking scripts from scratch.

    #### 2️⃣ Step 2: Open the Network Tab in DevTools
    * Go to the website's homepage, press **F12** (or right-click and select **Inspect**).
    * Navigate to the **Network** tab at the top.

    #### 3️⃣ Step 3: Configure Persistent Recording (Preserve Log)
    * Ensure the circular recording icon in the top-left corner of the DevTools panel is **red**.
    * ⚠️ **CRITICAL ELEMENT:** Absolutely check the **"Preserve log"** checkbox. If left unchecked, the browser will wipe all captured network traffic the moment you navigate away from the homepage!

    #### 4️⃣ Step 4: THE CRITICAL STEP – Full Cookie Acceptance
    * Refresh the page (`F5`). Wait for the privacy consent banner (CMP) to pop up.
    * **Click the primary button to accept all marketing and analytical tracking** (e.g., *'Accept All'*, *'Agree'*).
    * *Why?* Without explicit consent, Enterprise tracking systems remain blocked and won't ping the `.har` file!

    #### 5️⃣ Step 5: Execute the Full E-commerce Funnel
    * Click on any item to open the **product page**, then add it to the **cart**.
    * Continue to **checkout** (and, if possible, a test purchase). Item-level parameters and the heaviest hits often appear only there.
    * **Slowly scroll to the bottom of the page.** Modern lazy-loading frameworks delay enterprise tags until the user reaches the footer.

    #### 6️⃣ Step 6: Export the .HAR File
    * **Right-click** anywhere inside the list of recorded network requests in the DevTools panel.
    * Select **"Save all as HAR with content"** (the exact label differs between browser versions).
    """)

    st.success("🎯 Done!")
