#!/usr/bin/env python3
"""
Macro Mastery — static recipe page generator.

The app fetches recipes from Supabase at runtime, so search engines see an empty
shell and there is only ever one URL. This writes a real HTML page per recipe,
with the ingredients, method and macros in the markup rather than in JavaScript,
plus schema.org Recipe JSON-LD so Google can show rich results.

Run it whenever recipes change, then commit and push:

    python build_recipe_pages.py

Outputs:  recipes.json          static recipe data for the app
          recipes/<slug>.html   one per recipe
          recipes/index.html    browsable index
          sitemap.xml           every page on the site
          robots.txt            points crawlers at the sitemap

Nothing here talks to the live app — it only reads. Safe to re-run any time.
"""

import json
import os
import re
import html
import urllib.request
from datetime import date

SITE = "https://www.macromastery.uk"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "recipes")

SUPABASE_URL = "https://zvntjqazcmfmvyhhvpfl.supabase.co"
# The anon key is public by design — it is embedded in index.html and every
# request it can make is constrained by Row Level Security.
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp2bnRqcWF6Y21mbXZ5aGh2cGZsIiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3ODM4Nzg4NzgsImV4cCI6MjA5OTQ1NDg3OH0."
    "E_IkQdLrx42PcR7dOP9nkgHTt6ov2ZoMLOelQAIqpXo"
)

MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack", "shake"]


# ---------------------------------------------------------------- data

def fetch_recipes():
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/recipes?select=*&order=name",
        headers={"apikey": ANON_KEY},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_image_map():
    """Reuse the hand-picked photos already curated in index.html rather than
    keeping a second copy that can drift out of sync."""
    src = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    mdb = "https://www.themealdb.com/images/media/meals/{}.jpg"
    usp = "https://images.unsplash.com/{}?auto=format&fit=crop&w=900&q=70"
    imgs, fallbacks = {}, {}
    block = re.search(r"const RECIPE_IMG = \{(.*?)\n\};", src, re.S)
    if block:
        b = block.group(1)
        for name, fn, ident in re.findall(
            r"'([^']+)':\s*(mdb|usp)\('([^']+)'\)", b
        ):
            imgs[name] = (mdb if fn == "mdb" else usp).format(ident)
        # a few entries are plain URLs rather than mdb()/usp() helper calls
        for name, url in re.findall(r"'([^']+)':\s*\"(https?://[^\"]+)\"", b):
            imgs[name] = url
    fb = re.search(r"const MEAL_FALLBACK_IMG = \{(.*?)\};", src, re.S)
    if fb:
        for meal, fn, ident in re.findall(
            r"(\w+):\s*(mdb|usp)\('([^']+)'\)", fb.group(1)
        ):
            fallbacks[meal] = (mdb if fn == "mdb" else usp).format(ident)
    return imgs, fallbacks


def estimate_macros(r):
    """Mirrors estimateMacros() in index.html so the static pages never quote a
    different number from the app for the same recipe."""
    remaining = max(r["cal"] - r["protein"] * 4, 0)
    carb_share = 0.55
    if r["carb_source"] == "none":
        carb_share = 0.15
    elif r["carb_source"] in ("rice", "pasta", "oats", "potato", "bread", "quinoa", "wrap"):
        carb_share = 0.62
    carb_cal = remaining * carb_share
    return round(carb_cal / 4), round((remaining - carb_cal) / 9)


def slugify(name):
    s = name.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------- markup

def e(s):
    return html.escape(str(s), quote=True)


STYLE = """
:root{--ink:#141412;--cream:#F4EFE1;--card:#FFFDF6;--orange:#E8551D;
--orange-deep:#C4440F;--gold:#D9B44A;--line:#DED5BC;--line-strong:#C9BFA4;--muted:#6E695C;}
*{box-sizing:border-box;}
body{margin:0;background:var(--cream);color:var(--ink);font-family:'Work Sans',sans-serif;
-webkit-font-smoothing:antialiased;}
h1,h2,h3,h4,h5,h6{font-weight:400;}
.inner{max-width:1000px;margin:0 auto;padding:0 28px;}
.site-head{position:sticky;top:0;z-index:100;background:var(--cream);border-bottom:1px solid var(--ink);}
.head-inner{max-width:1220px;margin:0 auto;padding:16px 28px;display:flex;align-items:center;
justify-content:space-between;gap:20px;flex-wrap:wrap;}
.nav-logo{font-family:'Anton',sans-serif;font-size:22px;color:var(--ink);text-decoration:none;white-space:nowrap;}
.nav-logo b{color:var(--orange);font-weight:400;}
.nav-logo i{font-family:'Oswald',sans-serif;font-style:normal;font-size:11px;letter-spacing:.14em;
color:var(--muted);margin-left:4px;vertical-align:2px;}
.nav-links{display:flex;gap:26px;flex-wrap:wrap;}
.nav-links a{color:var(--ink);text-decoration:none;font-family:'Oswald',sans-serif;font-weight:600;
font-size:12px;letter-spacing:.14em;text-transform:uppercase;padding:4px 0;border-bottom:2px solid transparent;}
.nav-links a:hover,.nav-links a.here{border-bottom-color:var(--orange);color:var(--orange);}
.crumb{font-family:'Oswald',sans-serif;font-size:11px;letter-spacing:.16em;text-transform:uppercase;
color:var(--muted);margin:34px 0 14px;}
.crumb a{color:var(--orange-deep);text-decoration:none;}
h1{font-family:'Anton',sans-serif;font-size:clamp(38px,5.5vw,68px);line-height:1;text-transform:uppercase;
margin:0 0 16px;}
.lede{font-size:17px;line-height:1.7;color:#403B2E;margin:0 0 26px;max-width:640px;}
.hero-img{width:100%;max-width:760px;aspect-ratio:16/10;object-fit:cover;border:1.5px solid var(--ink);
border-radius:8px;display:block;margin-bottom:28px;background:var(--card);}
.tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px;}
.tag{font-family:'Oswald',sans-serif;font-weight:600;font-size:10.5px;letter-spacing:.1em;
text-transform:uppercase;padding:7px 15px;border-radius:999px;border:1.5px solid var(--line-strong);color:var(--muted);}
.tag.on{background:var(--ink);color:var(--cream);border-color:var(--ink);}
.macros{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(120px,100%),1fr));gap:0;
border:1.5px solid var(--ink);border-radius:8px;overflow:hidden;margin:0 0 34px;background:var(--card);}
.macro{padding:18px 16px;border-right:1px solid var(--line);}
.macro:last-child{border-right:none;}
.macro b{display:block;font-family:'Anton',sans-serif;font-size:30px;line-height:1;margin-bottom:5px;}
.macro span{font-family:'Oswald',sans-serif;font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);}
.macro.kcal b{color:var(--orange);}
.cols{display:grid;grid-template-columns:minmax(min(280px,100%),1fr) 1.4fr;gap:38px;align-items:start;}
h2{font-family:'Anton',sans-serif;font-size:26px;text-transform:uppercase;margin:0 0 16px;}
ul.ing{list-style:none;padding:0;margin:0;}
ul.ing li{display:flex;justify-content:space-between;gap:16px;padding:11px 0;border-bottom:1px solid var(--line);font-size:15px;}
ul.ing li span:last-child{color:var(--muted);white-space:nowrap;}
ol.steps{padding-left:0;margin:0;list-style:none;counter-reset:s;}
ol.steps li{counter-increment:s;position:relative;padding:0 0 18px 44px;line-height:1.72;font-size:15.5px;color:#3F3B2F;}
ol.steps li::before{content:counter(s);position:absolute;left:0;top:-2px;width:29px;height:29px;
border-radius:50%;background:var(--ink);color:var(--cream);font-family:'Anton',sans-serif;font-size:14px;
display:flex;align-items:center;justify-content:center;}
.tip{background:rgba(217,180,74,.22);border:1.5px solid var(--gold);border-radius:6px;padding:20px 22px;margin:30px 0 0;}
.tip strong{display:block;font-family:'Oswald',sans-serif;font-size:11px;letter-spacing:.14em;
text-transform:uppercase;margin-bottom:7px;}
.tip p{margin:0;font-size:14.5px;line-height:1.7;color:#3F3B2F;}
.cta{background:var(--ink);color:var(--cream);border-radius:8px;padding:32px 36px;margin:56px 0 0;
display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;}
.cta p{margin:0;font-family:'Anton',sans-serif;font-size:25px;text-transform:uppercase;line-height:1.15;}
.cta a{background:var(--orange);color:#FFF6ED;text-decoration:none;font-family:'Oswald',sans-serif;
font-weight:600;font-size:13px;letter-spacing:.13em;text-transform:uppercase;padding:15px 30px;border-radius:999px;white-space:nowrap;}
.cta a:hover{background:var(--orange-deep);}
.disclaimer{font-size:12.5px;line-height:1.7;color:var(--muted);margin:34px 0 0;max-width:720px;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(250px,100%),1fr));gap:22px;margin:0 0 44px;}
.rcard{border:1.5px solid var(--ink);border-radius:8px;overflow:hidden;background:var(--card);
text-decoration:none;color:var(--ink);display:flex;flex-direction:column;}
.rcard:hover{box-shadow:5px 5px 0 var(--ink);transform:translate(-2px,-2px);}
.rcard img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block;background:var(--cream);}
.rcard .body{padding:15px 17px 17px;}
.rcard h3{font-family:'Work Sans',sans-serif;font-weight:700;font-size:15.5px;margin:0 0 7px;line-height:1.3;}
.rcard .m{font-family:'Oswald',sans-serif;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);}
.meal-head{font-family:'Anton',sans-serif;font-size:30px;text-transform:uppercase;margin:44px 0 18px;}
.site-foot{background:var(--ink);color:var(--cream);padding:52px 0 36px;margin-top:80px;}
.foot-grid{display:flex;justify-content:space-between;gap:32px;flex-wrap:wrap;}
.foot-logo{font-family:'Anton',sans-serif;font-size:34px;line-height:1;margin:0 0 8px;}
.foot-tag{color:#A9A28E;font-size:14px;margin:0;}
.foot-links{display:flex;flex-direction:column;gap:11px;}
.foot-links a{color:var(--cream);text-decoration:none;font-family:'Oswald',sans-serif;font-weight:600;
font-size:11px;letter-spacing:.15em;text-transform:uppercase;}
.foot-links a:hover{color:var(--orange);}
.foot-bottom{margin-top:38px;padding-top:20px;border-top:1px solid #33312B;display:flex;
justify-content:space-between;gap:16px;flex-wrap:wrap;font-family:'Oswald',sans-serif;font-size:10px;
letter-spacing:.17em;text-transform:uppercase;color:#8B8471;}
@media(max-width:760px){.cols{grid-template-columns:1fr;gap:30px;}.inner{padding:0 18px;}
.cta{flex-direction:column;align-items:flex-start;}}
"""

FONTS = ("https://fonts.googleapis.com/css2?family=Anton&family=Oswald:wght@400;500;600;700"
         "&family=Work+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=Instrument+Serif:ital@0;1&display=swap")


def shell(title, desc, canonical, body, og_image=None, jsonld=None):
    ld = f'\n<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    og = f'\n<meta property="og:image" content="{e(og_image)}">' if og_image else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Macro Mastery">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canonical)}">{og}
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="{FONTS}">
<style>{STYLE}</style>{ld}
</head>
<body>
<header class="site-head">
  <div class="head-inner">
    <a class="nav-logo" href="/">MACRO <b>MASTERY</b><i>/UK</i></a>
    <nav class="nav-links">
      <a href="/#planner">Planner</a>
      <a href="/#matches">Matches</a>
      <a href="/recipes/" class="here">All recipes</a>
      <a href="/#how">How it works</a>
      <a href="/about.html">About</a>
    </nav>
  </div>
</header>
{body}
<footer class="site-foot">
  <div class="inner">
    <div class="foot-grid">
      <div>
        <p class="foot-logo">MACRO MASTERY</p>
        <p class="foot-tag">Eat for your goals. Without the spreadsheet.</p>
      </div>
      <div class="foot-links">
        <a href="/recipes/">All recipes</a>
        <a href="/about.html">About</a>
        <a href="/contact.html">Contact</a>
        <a href="/privacy.html">Privacy Policy</a>
      </div>
    </div>
    <div class="foot-bottom">
      <span>&copy; {date.today().year} Macro Mastery</span>
      <span>Made in the UK</span>
    </div>
  </div>
</footer>
<script defer src="/_vercel/insights/script.js"></script>
</body>
</html>
"""


def recipe_page(r, img):
    carbs, fat = estimate_macros(r)
    slug = slugify(r["name"])
    url = f"{SITE}/recipes/{slug}.html"
    diet = r.get("diet") or []
    # "halal" is not surfaced anywhere in the app, so it is not surfaced here
    shown = [d for d in diet if d != "halal"]

    desc = (f"{r['name']} — {r['cal']} kcal and {r['protein']}g protein per serving, "
            f"about £{float(r['price']):.2f}. Full ingredients, method and "
            f"meal-prep notes for this UK {r['meal']} recipe.")

    tags = "".join(f'<span class="tag on">{e(d)}</span>' for d in shown)
    tags += f'<span class="tag">{e(r["skill"])}</span>'
    if r.get("meal_prep_friendly"):
        tags += '<span class="tag">Meal-prep friendly</span>'

    ings = "".join(
        f"<li><span>{e(n)}</span><span>{e(q)}</span></li>" for n, q in r["ingredients"]
    )
    steps = "".join(f"<li>{e(s)}</li>" for s in r["steps"])
    tip = ""
    if r.get("meal_prep_tip"):
        tip = (f'<div class="tip"><strong>Meal-prep note</strong>'
               f'<p>{e(r["meal_prep_tip"])}</p></div>')

    jsonld = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": r["name"],
        "image": [img],
        "description": desc,
        "recipeCategory": r["meal"],
        "recipeYield": "1 serving",
        "recipeIngredient": [f"{q} {n}" for n, q in r["ingredients"]],
        "recipeInstructions": [
            {"@type": "HowToStep", "position": i + 1, "text": s}
            for i, s in enumerate(r["steps"])
        ],
        "nutrition": {
            "@type": "NutritionInformation",
            "servingSize": "1 serving",
            "calories": f"{r['cal']} kcal",
            "proteinContent": f"{r['protein']} g",
            "carbohydrateContent": f"{carbs} g",
            "fatContent": f"{fat} g",
        },
        "author": {"@type": "Organization", "name": "Macro Mastery"},
        "url": url,
    }
    if r.get("video"):
        jsonld["video"] = {"@type": "VideoObject", "name": r["name"], "contentUrl": r["video"]}
    if shown:
        jsonld["suitableForDiet"] = [
            {"vegan": "https://schema.org/VeganDiet",
             "vegetarian": "https://schema.org/VegetarianDiet",
             "gluten-free": "https://schema.org/GlutenFreeDiet"}[d]
            for d in shown if d in ("vegan", "vegetarian", "gluten-free")
        ] or None
        if not jsonld.get("suitableForDiet"):
            jsonld.pop("suitableForDiet", None)

    video_line = ""
    if r.get("video"):
        video_line = (f'<p class="lede" style="margin-top:-10px;">'
                      f'<a href="{e(r["video"])}" rel="noopener" target="_blank" '
                      f'style="color:var(--orange-deep);font-weight:600;">Watch a video of this dish &rarr;</a></p>')

    body = f"""
<div class="inner">
  <p class="crumb"><a href="/">Home</a> / <a href="/recipes/">Recipes</a> / {e(r['meal'])}</p>
  <h1>{e(r['name'])}</h1>
  <p class="lede">A UK {e(r['meal'])} recipe with {r['cal']} kcal and {r['protein']}g of protein
     per serving, costing roughly &pound;{float(r['price']):.2f} to make.</p>
  {video_line}
  <img class="hero-img" src="{e(img)}" alt="{e(r['name'])}" loading="lazy">
  <div class="tags">{tags}</div>
  <div class="macros">
    <div class="macro kcal"><b>{r['cal']}</b><span>kcal</span></div>
    <div class="macro"><b>{r['protein']}g</b><span>Protein</span></div>
    <div class="macro"><b>{carbs}g</b><span>Carbs (est.)</span></div>
    <div class="macro"><b>{fat}g</b><span>Fat (est.)</span></div>
    <div class="macro"><b>&pound;{float(r['price']):.2f}</b><span>Per serving</span></div>
  </div>
  <div class="cols">
    <div>
      <h2>Ingredients</h2>
      <ul class="ing">{ings}</ul>
    </div>
    <div>
      <h2>Method</h2>
      <ol class="steps">{steps}</ol>
      {tip}
    </div>
  </div>
  <div class="cta">
    <p>Want a whole week<br>built around your macros?</p>
    <a href="/#planner">Plan my week &rarr;</a>
  </div>
  <p class="disclaimer">Calories and protein are set per recipe; carbs and fat are estimated from the
    remaining calories and the recipe's main carb source, so treat them as a close guide rather than a
    lab measurement. Prices are rough per-serving estimates for UK supermarkets and vary by store and
    season. Nothing here is medical or dietary advice.</p>
</div>
"""
    return shell(f"{r['name']} — {r['cal']} kcal, {r['protein']}g protein | Macro Mastery",
                 desc, url, body, og_image=img, jsonld=jsonld)


def index_page(recipes, imgs):
    sections = ""
    for meal in MEAL_ORDER:
        group = [r for r in recipes if r["meal"] == meal]
        if not group:
            continue
        cards = ""
        for r in group:
            cards += (
                f'<a class="rcard" href="/recipes/{slugify(r["name"])}.html">'
                f'<img src="{e(imgs[r["name"]])}" alt="{e(r["name"])}" loading="lazy">'
                f'<div class="body"><h3>{e(r["name"])}</h3>'
                f'<p class="m">{r["cal"]} kcal &middot; {r["protein"]}g protein &middot; '
                f'&pound;{float(r["price"]):.2f}</p></div></a>'
            )
        sections += f'<h2 class="meal-head">{meal.title()} <span style="color:var(--muted);font-size:18px;">({len(group)})</span></h2><div class="grid">{cards}</div>'

    desc = (f"All {len(recipes)} Macro Mastery recipes with calories, protein and UK supermarket "
            f"costs per serving — breakfast, lunch, dinner, snacks and shakes.")
    body = f"""
<div class="inner">
  <p class="crumb"><a href="/">Home</a> / Recipes</p>
  <h1>All recipes</h1>
  <p class="lede">Every recipe in the planner, with calories, protein and a rough UK supermarket cost
     per serving. All {len(recipes)} come with full written instructions and meal-prep notes.</p>
  {sections}
  <div class="cta">
    <p>Stop picking meals<br>one at a time.</p>
    <a href="/#planner">Plan my week &rarr;</a>
  </div>
</div>
"""
    # plain "&" here — shell() escapes it, so an entity would be double-escaped
    return shell(f"All {len(recipes)} recipes — calories, protein & UK cost | Macro Mastery",
                 desc, f"{SITE}/recipes/", body)


# ---------------------------------------------------------------- run

def main():
    recipes = fetch_recipes()
    img_map, fallbacks = parse_image_map()
    imgs = {r["name"]: img_map.get(r["name"]) or fallbacks.get(r["meal"]) or fallbacks["dinner"]
            for r in recipes}

    os.makedirs(OUT, exist_ok=True)
    missing = [r["name"] for r in recipes if r["name"] not in img_map]

    for r in recipes:
        path = os.path.join(OUT, slugify(r["name"]) + ".html")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(recipe_page(r, imgs[r["name"]]))

    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8", newline="") as f:
        f.write(index_page(recipes, imgs))

    # A static copy of the recipe library for the app to load.
    #
    # Without this, every visitor fetches all recipes from Supabase on page load
    # — a database round trip on the critical path, uncached, and the single
    # biggest consumer of the bandwidth allowance. As a file on Vercel it is
    # served from the CDN edge instead: no database read, no cold query.
    #
    # Only the columns index.html actually uses are included, which keeps it
    # meaningfully smaller than select=*.
    keep = ("name", "meal", "diet", "skill", "cal", "protein", "price", "pp",
            "icon", "protein_source", "carb_source", "video", "ingredients",
            "steps", "meal_prep_friendly", "meal_prep_tip")
    slim = [{k: r.get(k) for k in keep} for r in recipes]
    with open(os.path.join(HERE, "recipes.json"), "w", encoding="utf-8", newline="") as f:
        json.dump(slim, f, ensure_ascii=False, separators=(",", ":"))

    today = date.today().isoformat()
    urls = [(f"{SITE}/", "1.0"), (f"{SITE}/recipes/", "0.9"),
            (f"{SITE}/about.html", "0.5"), (f"{SITE}/contact.html", "0.4"),
            (f"{SITE}/privacy.html", "0.3"), (f"{SITE}/terms.html", "0.3"),
            (f"{SITE}/refund.html", "0.3")]
    urls += [(f"{SITE}/recipes/{slugify(r['name'])}.html", "0.8") for r in recipes]
    entries = "".join(
        f"\n  <url><loc>{u}</loc><lastmod>{today}</lastmod><priority>{p}</priority></url>"
        for u, p in urls
    )
    with open(os.path.join(HERE, "sitemap.xml"), "w", encoding="utf-8", newline="") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f'{entries}\n</urlset>\n')

    with open(os.path.join(HERE, "robots.txt"), "w", encoding="utf-8", newline="") as f:
        f.write("User-agent: *\nAllow: /\n\n"
                f"Sitemap: {SITE}/sitemap.xml\n")

    print(f"recipes generated : {len(recipes)}")
    print(f"recipes.json      : {os.path.getsize(os.path.join(HERE, 'recipes.json'))//1024} KB")
    print(f"index page        : recipes/index.html")
    print(f"sitemap urls      : {len(urls)}")
    print(f"robots.txt        : written")
    if missing:
        print(f"\nNo hand-picked photo (using meal fallback) for {len(missing)}:")
        for n in missing:
            print("   -", n)


if __name__ == "__main__":
    main()
