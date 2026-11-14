#!/usr/bin/env python3
import urllib.request
import subprocess
import json
import os
import sys

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rules_dir = os.path.join(base_dir, "rules")
    os.makedirs(rules_dir, exist_ok=True)

    temp_srs = os.path.join(base_dir, "temp_upstream_google.srs")
    temp_json = os.path.join(base_dir, "temp_upstream_google.json")
    out_json = os.path.join(rules_dir, "google.json")
    out_srs = os.path.join(rules_dir, "google.srs")

    # 1. Download upstream SagerNet geosite-google.srs
    upstream_url = "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-google.srs"
    print(f"Downloading upstream ruleset from: {upstream_url}")
    urllib.request.urlretrieve(upstream_url, temp_srs)

    # 2. Decompile to json using sing-box
    sing_box_cmd = "sing-box"
    # Fallback to local homebrew path if not found in PATH
    if not any(os.access(os.path.join(p, "sing-box"), os.X_OK) for p in os.environ.get("PATH", "").split(os.pathsep)):
        if os.path.exists("/opt/homebrew/bin/sing-box"):
            sing_box_cmd = "/opt/homebrew/bin/sing-box"

    print("Decompiling upstream srs to json...")
    subprocess.run([sing_box_cmd, "rule-set", "decompile", temp_srs, "-o", temp_json], check=True)

    # 3. Filter out YouTube-related domains and regexes
    with open(temp_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    def is_youtube(s):
        s_lower = s.lower()
        return (
            "youtube" in s_lower or
            "googlevideo" in s_lower or
            "youtu.be" in s_lower or
            "ytimg" in s_lower or
            "yt.be" in s_lower or
            s_lower == "yt3.googleusercontent.com"
        )

    cleaned_rules = []
    for r in data.get("rules", []):
        domains = [d for d in r.get("domain", []) if not is_youtube(d)]
        suffixes = [s for s in r.get("domain_suffix", []) if not is_youtube(s)]
        regexes = [x for x in r.get("domain_regex", []) if not ("googlevideo" in x or "youtube" in x or "xn--ngstr-lra8j" in x)]
        keywords = [k for k in r.get("domain_keyword", []) if not ("youtube" in k.lower() or "googlevideo" in k.lower())]

        cleaned_rule = {}
        if domains:
            cleaned_rule["domain"] = sorted(list(set(domains)))
        if suffixes:
            cleaned_rule["domain_suffix"] = sorted(list(set(suffixes)))
        if keywords:
            cleaned_rule["domain_keyword"] = sorted(list(set(keywords)))
        if regexes:
            cleaned_rule["domain_regex"] = regexes

        if cleaned_rule:
            cleaned_rules.append(cleaned_rule)

    output_data = {
        "version": data.get("version", 2),
        "rules": cleaned_rules
    }

    # 4. Save google.json
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Saved filtered json to: {out_json}")

    # 5. Compile to google.srs
    print("Compiling filtered json to srs...")
    subprocess.run([sing_box_cmd, "rule-set", "compile", out_json, "-o", out_srs], check=True)
    print(f"Successfully generated: {out_srs}")

    # Cleanup temp files
    if os.path.exists(temp_srs):
        os.remove(temp_srs)
    if os.path.exists(temp_json):
        os.remove(temp_json)

if __name__ == "__main__":
    main()
