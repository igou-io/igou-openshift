---
name: storescrape
description: Query grocery flyer stores, flyers, and deals using the local storescrape CLI.
version: 1.8.0
metadata:
  hermes:
    tags:
      - grocery
      - flyer
      - deals
      - flipp
      - shopping
      - storescrape
    category: grocery
---

# Storescrape CLI

## When to Use

Use this skill when the user asks for grocery deals, flyer items, store circulars, weekly ads, prices, or deal comparisons by ZIP/postal code.

## Procedure

1. Identify the postal/ZIP code. If the user did not provide one, use the default only if project instructions define one; otherwise ask.
2. Identify search terms. Convert natural language into concise comma-separated queries.
   - "cheap steaks" -> `steak,beef`
   - "chicken breast deals" -> `chicken,chicken breast`
   - "produce" -> `produce,fruit,vegetables`
3. Run the CLI with JSON output. Pick the invocation for your environment:

On the host (CLI sessions, where `storescrape` is on PATH):

```bash
storescrape deals <postal_code> -q "<terms>" -j --compact --limit 25
```

In the terminal sandbox (cron jobs, Docker — `storescrape` is NOT on PATH there and the `.venv/bin/storescrape` entry point does not execute; the repo is mounted at `/workspace/storescrape`):

```bash
cd /workspace/storescrape && .venv/bin/python3 -m storescrape.cli deals <postal_code> -q "<terms>" -j --compact --limit 25
```

4. Summarize results by merchant and deal quality.
5. Always include validity dates.
6. Mention uncertainty if price units or package sizes are ambiguous.

## Useful Commands

List stores:

```bash
storescrape stores 23236 -j
```

List flyers:

```bash
storescrape flyers 23236 -j
```

Search deals:

```bash
storescrape deals 23236 -q "steak,beef" -j --compact --limit 25
```

## Weekly Flyer Analysis (scheduled runs)

Use this procedure when asked for a full flyer analysis (e.g., from a cron job) rather than a single-item lookup. Default ZIP is 23236 unless the prompt specifies another.

1. Run one `deals` query per protein plus the grocery categories (each is fast, ~4s). ALWAYS run every query fresh — never reuse result files left in /tmp by a previous run; flyers change between runs. Flyer item naming has NO methodology — the same cut appears as "chuck", "pot roast", "London broil", etc. — so the term lists are deliberately long and exhaustive. Run them exactly as written. Scheduled runs execute in the terminal sandbox, so use the sandbox invocation:

Do NOT pass `--limit` — limits silently drop real deals from smaller merchants (Lidl deals were once lost because Publix and Restaurant Depot items filled the capped result set before filtering). Every query pipes through `jq` to drop the bulky, useless `image_url` field — keep that pipe; it keeps full result sets within tool output limits. The pork/cured-meats net is split into two queries for the same reason.

```bash
cd /workspace/storescrape
# Proteins — one query per protein, wide synonym nets, NO --limit
.venv/bin/python3 -m storescrape.cli deals 23236 -q "beef,steak,ground beef,chuck,ribeye,rib eye,sirloin,brisket,t-bone,porterhouse,tenderloin,filet mignon,strip steak,ny strip,new york strip,flank,skirt steak,round roast,rump roast,chuck roast,pot roast,eye of round,top round,bottom round,short ribs,beef ribs,oxtail,london broil,tri-tip,stew meat,cube steak,burger,patties,angus,wagyu,corned beef" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "chicken,chicken breast,chicken thigh,thighs,drumsticks,drumettes,wings,wingettes,whole chicken,leg quarters,chicken leg,tenders,tenderloins,ground chicken,rotisserie,cornish hen,chicken sausage,fryer,broiler,gizzards,chicken livers" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "pork,ribs,baby back,spareribs,spare ribs,st louis ribs,country ribs,pork chop,pork loin,pork tenderloin,pork shoulder,pork butt,boston butt,picnic roast,pulled pork,ground pork,pork belly" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "bacon,ham,sausage,bratwurst,kielbasa,chorizo,andouille,italian sausage,breakfast sausage,hot dogs,franks,pancetta,prosciutto,salami,pepperoni" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "shrimp,prawns,crab,crab legs,snow crab,king crab,lobster,lobster tail,scallops,oysters,clams,mussels,crawfish,crayfish,calamari,squid,octopus,langostino" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "fish,salmon,tilapia,cod,tuna,catfish,trout,flounder,mahi,halibut,swordfish,snapper,haddock,perch,sardines,anchovies,whiting,pollock,swai,branzino,sea bass,grouper,walleye,fish fillet,fish sticks,smoked salmon,lox,ahi" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "turkey,ground turkey,turkey breast,lamb,lamb chops,leg of lamb,rack of lamb,ground lamb,duck,duck breast,bison,ground bison,goat,venison,elk,rabbit,quail,pheasant,goose,veal,frog legs,alligator,ostrich,mutton" -j --compact | jq -c 'map(del(.image_url))'
# Other grocery categories — NO --limit
.venv/bin/python3 -m storescrape.cli deals 23236 -q "fruit,vegetables,berries,tomatoes,peppers,salad" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "milk,eggs,cheese,butter,yogurt" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "bread,cereal,pasta,rice,coffee" -j --compact | jq -c 'map(del(.image_url))'
.venv/bin/python3 -m storescrape.cli deals 23236 -q "frozen,ice cream,snacks" -j --compact | jq -c 'map(del(.image_url))'
```

If any query's JSON output comes back truncated (parse error / output cut off), split that query's term list into two halves and re-run each half — never fall back to `--limit`.

(On the host, plain `storescrape deals ...` works instead.) Do not use `execute_code` for these queries in scheduled runs — it is blocked for cron jobs; use the terminal tool directly.

2. Clean the results:
   - Drop items whose `valid_to` has already passed.
   - Drop items with an empty `price` unless the name clearly describes the deal (e.g., "buy one get one").
   - Deduplicate identical merchant + name + price entries, including across queries (the wide term nets overlap).
   - Discard ALL items from any Publix banner ("Publix", "Publix Liquors", etc.) — excluded entirely from the report.
   - Set aside ALL Restaurant Depot items into their own bucket. They are wholesale/bulk prices and must NOT appear in the main sections or be ranked against retail prices — they get their own analysis block (step 5).
3. Reassign and filter protein matches — term matching is substring-based, so expect junk:
   - Classify each item by what its FULL NAME says it is, not by which query returned it: "Salmon Burgers" from the beef query → fish; "Turkey Sausage" from the pork query → other; "Pork Tenderloin" from the beef query → pork; "Chicken Sausage" → chicken.
   - Discard non-food and brand-name false positives: "beefsteak tomatoes", "Grey Goose vodka", "Turkey Hill iced tea", "Buffalo sauce"/"buffalo wings sauce", pet food, toys, furniture.
   - Discard plant-based imitations (meatless, plant-based, vegan, tofu) from protein sections.
   - Prepared deli/frozen items that genuinely contain the protein (rotisserie chicken, lunch meat, smoked sausage, fish sticks) belong in that protein's section — prefer raw cuts when ranking, but include prepared standouts.
4. Analyze (retail merchants only — no Restaurant Depot, no Publix):
   - Within each protein, identify the cheapest offer per common cut (e.g., cheapest ground beef, cheapest chicken breast, cheapest bacon) and the price spread across merchants.
   - Flag standout deals: staple prices well below typical (e.g., chicken breast under $2.50/lb, ground beef under $4/lb, eggs under $2/dozen).
   - Flag deals ending within 2 days as "last chance".
   - Note which merchant has the strongest overall flyer this cycle.
5. Restaurant Depot analysis (separate, from the set-aside bucket):
   - Rank its best protein buys per lb across beef, chicken, pork, shellfish, fish, specialty.
   - Where the same cut appears at a retail merchant, state the bulk-vs-retail delta (e.g., "catfish fillets $3.89 vs Food Lion $7.99 — bulk saves ~51%").
   - Note that RD flyers typically run monthly (longer validity) and prices are wholesale/bulk quantities.
5b. Update the meat-prices spreadsheet through the main agent's `gdrive` MCP tools (MANDATORY for scheduled meat scans, BEFORE delivery). The target is the existing `hermes/meat-prices-23236` spreadsheet, ID `1cM4iq_iJyNS9peZvMSK9-kWqssUfupBEW-ERukle7Ss`, data tab `prices`, view tab `latest`. Never use a service-account key, Google API HTTP request, terminal-side sheet writer, or the retired `sheets_append.py` helper. MCP calls run in the main agent, not its terminal sandbox.
   1. Build one row per featured meat deal from steps 2–5: the best offer per merchant and normalized cut. A chicken-thigh-only scan writes only its chicken-thigh deals. Soda-only scans do not write meat rows. Include Restaurant Depot with `notes` containing `wholesale/bulk`; exclude Publix. Every row uses today's America/New_York date as the scan date. Preserve the existing columns and their order:

      `date, category, cut, merchant, item, price, unit, price_per_lb, valid_from, valid_to, notes`

      Category is beef|chicken|pork|cured|shellfish|fish|other. Cut is normalized lowercase; use `chicken thigh` for thigh offers. Price must be a finite nonnegative decimal, not a deal phrase. Compute per-item prices for multi-buy offers and explain in notes. `price_per_lb` is blank unless derivable; unit is blank unless stated. Dates must be real YYYY-MM-DD dates and validity must include today. Never invent a price, quantity, unit, or deal.
   2. Use `gdrive.getSpreadsheetInfo` and `gdrive.getGoogleSheetContent` to confirm the title and `prices!A1:K1` header. Stop and report a sheet error if the target/header differs; do not create a spreadsheet or overwrite its schema. Keep historical rows and the `latest` formula intact.
   3. Make the write idempotent. Read `prices!A2:A` with FORMATTED_VALUE, identify today's row numbers, and read only those rows' A:K values. `getGoogleSheetContent` labels rows relative to the requested range, so calculate absolute row numbers from the A2 offset, or use `getGoogleSheetCells` for absolute A1 addresses. Match on (scan date, category, normalized cut, merchant), case-insensitively for text. Skip unchanged matching rows, update changed matches at their exact row, and append only missing keys. Deduplicate this run's keys before writing. Never clear an entire date or tab: another job's rows may share that date. Before retrying an uncertain write, re-read today's rows so a successful first attempt is not duplicated.
   4. Write via `gdrive.batchUpdateGoogleSheetValues` for changed rows and `gdrive.appendSpreadsheetRows` for missing rows, using explicit spreadsheet ID, `prices` ranges, and valueInputOption USER_ENTERED. This preserves numeric prices and actual date cells so the existing `latest` formula continues to work. Sanitize the payload before calling either tool: dates and prices must be validated, generated date/decimal strings; prefix EVERY text value in columns B,C,D,E,G,K with one apostrophe so flyer text is stored literally and cannot become a formula. Blank optional cells use an empty string. Never submit unsanitized flyer text in USER_ENTERED mode. Append in batches of at most 50 rows and keep the returned updated range.
   5. Read back each written range with FORMATTED_VALUE and confirm dates, categories, cuts, merchants, item descriptions, prices and the expected row count. Confirm `latest!A2:K` displays this scan rather than an error. Only then say the sheet update succeeded, including the number appended/updated/skipped. If no qualifying meat deals exist, write nothing and report that honestly. After three failed MCP attempts, continue the normal report with `⚠ sheet update failed`; never claim success or expose credentials or raw API responses.
6. Format for Slack (keep the whole report under ~70 lines):
   - One headline line: the single best RETAIL deal of the cycle.
   - One section per protein — Beef, Chicken, Pork, Shellfish, Fish, Specialty (turkey/lamb/duck/bison/game) — with the top 3–5 retail picks each: `Store — Item — $price (valid through date)`.
   - One short section each for Produce, Dairy, Pantry, Frozen & Snacks with the top 3 retail picks.
   - A "best store to hit" recommendation with one sentence of reasoning (retail only).
   - THEN a clearly separated `📦 Restaurant Depot (wholesale)` block at the end: its own best-buys list and the bulk-vs-retail comparisons from step 5. Omit the block if RD returned nothing.
   - Prices come without package sizes/units from the API — say "per lb"/"each" only when the item name states it, otherwise leave the price bare.
7. If a category or protein returns nothing usable, omit its section. If everything is empty, report which ZIP and terms were searched instead of an empty report.
8. Delivery (scheduled runs only). Slack splits any message over ~4,000 characters into multiple top-level messages, so the report is delivered as an anchor + thread via the Slack API from the terminal (the `send_message` tool is not available in cron runs). THE RUN IS NOT COMPLETE UNTIL BOTH POSTS BELOW HAVE SUCCEEDED — composing the report is not delivering it:
   1. Write the compact digest to a file, then post it as the anchor message. Digest contents: the headline deal, one best pick per protein, the best-store recommendation, and a final line `🧵 Full report in thread`. MUST be under 3,500 characters. `$SLACK_BOT_TOKEN` is present in the sandbox environment — reference it, NEVER echo/print it.

```bash
cat > /tmp/digest.json <<'JSON'
{"channel": "C0BDFHWRQM7", "text": "<digest text here, \n for newlines>"}
JSON
curl -s -X POST https://slack.com/api/chat.postMessage \
  -H "Authorization: Bearer $SLACK_BOT_TOKEN" -H "Content-Type: application/json" \
  -d @/tmp/digest.json | jq '{ok, ts, error}'
```

   2. Confirm `"ok": true` and note the returned `ts`. Post the FULL report (step 6's sections, including the Restaurant Depot block) as ONE reply in that thread by adding `"thread_ts": "<ts>"` to the JSON payload. The full report may exceed 4,000 characters — Slack will split it into consecutive messages that all stay inside the thread, which is fine. Confirm `"ok": true` again.
   3. After both posts succeed, end with a final response of exactly `[SILENT]`.
   4. If the anchor post fails (`"ok": false` or curl error), do not keep retrying — put the entire report in your final response instead so cron auto-delivery picks it up as a fallback.

## Verification

- Confirm output is valid JSON.
- Confirm `valid_to` has not passed.
- Confirm the merchant matches the requested store if the user specified one.
- For scheduled meat scans: confirm the gdrive MCP write and readback succeeded before delivery; report sheet failures explicitly.
