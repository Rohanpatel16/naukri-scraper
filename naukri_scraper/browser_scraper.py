"""High-Performance Async Multi-Tab Browser Scraper for Naukri.com.

Optimized for high speed, stability on cloud CI/CD runners (GitHub Actions / Linux),
and local environments with 100% data fidelity:
- Async parallel multi-tab search scraping
- Stealth browser flags & anti-automation evasion
- Built-in instant resolution for top 100+ major employers (0ms latency)
- Paced live tab enrichment for remaining companies with live terminal progress
- Hard timeouts and clean resource disposal (guaranteed zero hangs)
"""

from __future__ import annotations

import asyncio
import datetime
import html
import json
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Set

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .config import DEFAULT_HEADERS
from .parser import parse_job_url

logger = logging.getLogger(__name__)

# Global cache for company website lookups across runs/batches
_COMPANY_WEBSITE_CACHE: Dict[str, str] = {}

# Instant domain registry for prominent employers in India (0ms lookup, zero network calls)
KNOWN_COMPANY_DOMAINS: Dict[str, str] = {
    "2coms": "https://www.2coms.com/",
    "academian india": "https://academian.com/",
    "accelirate softech": "https://www.accelirate.com/",
    "accenture": "https://www.accenture.com/",
    "acl digital": "https://www.acldigital.com/",
    "adani": "https://www.adani.com/",
    "adani group": "https://www.adani.com/",
    "airtel": "https://www.airtel.in/",
    "airtel payments bank": "https://www.airtelpayments.bank.in/",
    "ais business solution": "https://www.americaninfosource.com/",
    "alaric ventures": "https://www.alaricventures.com/",
    "algoleap technologies": "https://www.algoleap.com",
    "allied digital": "https://www.allieddigital.net",
    "allscripts(india) llp, ultimately a subsidiary of altera digital health inc.,[altera india]": "https://veradigm.com/",
    "amar ujala": "https://www.amarujala.com/",
    "amazon": "https://www.amazon.jobs/",
    "amneal pharmaceuticals": "https://www.amneal.com",
    "andor tech": "http://www.andortech.com",
    "aon": "https://www.aon.com",
    "apa engineering": "https://www.apaengineering.com",
    "apexon": "https://www.apexon.com/",
    "app innovation technologies": "https://www.aitechindia.com/",
    "apptad": "https://apptad.com/",
    "ascent e digit solutions": "http://www.aedindia.com/",
    "aspire systems": "https://www.aspiresys.com",
    "atria convergence technologies (act)": "https://www.actcorp.in/",
    "bajaj finance": "https://www.bajajfinserv.in/",
    "bharti airtel": "https://www.airtel.in/",
    "birlasoft": "https://www.birlasoft.com/",
    "bitcot technologies": "https://www.bitcot.com/",
    "bitsilica": "https://www.bitsilica.com/",
    "bobcard": "http://www.bobcard.co.in/",
    "boldtek": "https://www.boldtek.com/",
    "bounteous": "https://www.bounteous.com/",
    "bridgenext": "https://www.bridgenext.com/",
    "ca one tech": "http://www.ca-one.com/",
    "calsoft": "https://calsoftinc.com/",
    "capgemini": "https://www.capgemini.com/",
    "cargill": "https://www.cargill.com/",
    "ceil": "https://vishalexpert.com/",
    "celusion technologies": "https://www.celusion.com",
    "centroid": "https://www.centroidcnc.com",
    "cgi": "https://www.cgi.com/india/en/",
    "cisco": "https://www.cisco.com/",
    "cloudxtreme": "https://www.cloudxtreme.info/",
    "cms it services": "https://www.cmsitservices.com/",
    "coforge": "https://www.coforge.com/",
    "cognizant": "https://www.cognizant.com/",
    "cognizant technology solutions": "https://www.cognizant.com/",
    "colortokens": "https://colortokens.com/",
    "cyber managers software services": "https://www.cmss.in/",
    "cyient": "https://www.cyient.com/",
    "datamark bpo service": "https://www.datamark.net",
    "datamatics": "https://www.datamatics.com/",
    "dell": "https://www.dell.com/",
    "dell technologies": "https://www.dell.com/",
    "deloitte": "https://www.deloitte.com/",
    "deloitte shared services india": "https://www.deloitte.com/ui/en/careers/careers.html?icid=top_careers&id=ui:2or:3or:4usirbmfy27:5:6car:20260730::usicarnaukri",
    "deloitte us-india offices": "https://www.deloitte.com/ui/en/careers/careers.html?icid=top_careers&id=ui:2or:3or:4usirbmfy27:5:6car:20260730::usicarnaukri",
    "dinesh engineers": "https://www.depl.co.in",
    "doyen infosolutions": "https://www.doyen.co.in",
    "easemytrip": "https://www.easemytrip.com/",
    "eclat health solutions": "https://www.eclathealth.com",
    "eclerx": "https://eclerx.com/",
    "eclerx services": "https://eclerx.com/",
    "edgeverve systems": "https://www.edgeverve.com/",
    "eisneramper": "https://www.eisneramper.com/",
    "embarkgcc services": "https://embarkgrp.com/",
    "embitel technologies": "https://www.embitel.com/",
    "emids technologies": "https://www.emids.com/",
    "emsec": "https://www.emsec.uk/",
    "epam": "https://www.epam.com/",
    "epam systems": "https://www.epam.com/",
    "epiroc mining india": "https://www.epiroc.com/en-in",
    "equiniti india": "https://www.equiniti-india.com/",
    "ernst & young": "https://www.ey.com/",
    "eruvaka technologies": "https://www.eruvaka.com",
    "evolute group": "https://www.evolute.in/",
    "expert solution technologies": "https://expsoltech.com/",
    "expleo": "https://expleo.com/",
    "ey": "https://www.ey.com/",
    "ez-xbrl solutions": "https://www.ez-xbrl.com",
    "feuji software solutions": "https://www.feuji.com/",
    "finastra": "https://www.finastra.com/",
    "fis": "http://www.fisglobal.com/",
    "fractal analytics": "https://fractal.ai/",
    "galaxy health insurance company": "https://www.galaxyhealth.com/",
    "ganpat university": "https://www.ganpatuniversity.ac.in",
    "geak minds": "https://geakminds.com/",
    "google": "https://careers.google.com/",
    "grazitti interactive": "https://www.grazitti.com/",
    "gruve": "https://www.gruve.ai/",
    "gsr business services": "https://www.gsr-inc.com",
    "gtpl kcbpl": "http://www.gtplkcbpl.com",
    "hamon technologies": "https://hamon.in/",
    "han river technology": "https://www.hanriver.co",
    "happiest minds": "https://www.happiestminds.com/",
    "happiest minds technologies": "https://www.happiestminds.com/",
    "harbinger systems": "https://www.harbinger-systems.com",
    "hcl technologies": "https://www.hcltech.com/",
    "hcltech": "https://www.hcltech.com/",
    "hexaware": "https://www.hexaware.com/",
    "hexaware technologies": "https://www.hexaware.com/",
    "highspring india llp": "http://vacobinary.in/",
    "hinduja tech": "https://hindujatech.com/",
    "honeybee tech solutions": "http://honeybeetechsolutions.com/",
    "hp": "https://www.hp.com/",
    "hurix": "https://www.hurix.com/",
    "hype marketer": "https://www.tranzindia.in/",
    "hyundai autoever": "https://www.hyundai-autoever.com",
    "ibm": "https://www.ibm.com/",
    "id softsource": "https://idsoftsource.com/",
    "impressico business solutions": "https://www.impressico.com/",
    "inceptive consulting": "http://inceptive.consulting/",
    "indus towers": "https://www.industowers.com",
    "infinite": "https://www.infinite.com/",
    "infosys": "https://www.infosys.com/",
    "infotel it consulting": "http://www.infotel.in/",
    "infovision labs": "http://www.infovision.com/",
    "inspirisys": "https://www.inspirisys.com/",
    "intel": "https://www.intel.com/",
    "intellics global services": "https://intellicsglobal.com/",
    "intrics solutions": "https://rdsolutions.io/",
    "invisia bpo solutions": "https://www.invisia.us/",
    "iq-eq": "https://iqeq.com/",
    "iqdynamics technologies": "https://www.iqdynamics.com/",
    "jio": "https://www.jio.com/",
    "kairos technologies": "https://www.kairostech.com/",
    "kaizen infotech": "https://www.kaizeninfotech.co.in",
    "kapil group": "https://www.kapilgroup.com",
    "kapitus strategy services": "https://kapitus.com",
    "kellton": "https://www.kellton.com/",
    "kg information systems (kgisl)": "https://www.kgisl.com",
    "kiya.ai": "https://www.kiya.ai/",
    "kochasoft": "https://kochasoft.com/",
    "kpmg": "https://www.kpmg.com/",
    "l&t": "https://www.larsentoubro.com/",
    "larsen & toubro": "https://www.larsentoubro.com/",
    "larsen & toubro (l&t)": "https://www.larsentoubro.com/",
    "lenovo": "https://www.lenovo.com/",
    "lti": "https://www.ltimindtree.com/",
    "ltimindtree": "https://www.ltimindtree.com/",
    "ltm": "https://www.ltm.com/",
    "mastek": "https://www.mastek.com/",
    "matrix business services": "http://www.matrixbsindia.com/",
    "maveric": "http://www.maveric-systems.com/careers",
    "mergen infotech": "https://mergeninfotech.com/",
    "merit data and technology": "https://www.meritdata-tech.com/",
    "microsoft": "https://www.microsoft.com/",
    "milestone technologies": "https://milestone.tech/",
    "mindshare": "https://www.mindshareworld.com/",
    "mindtree": "https://www.ltimindtree.com/",
    "miraki tech": "http://www.mirakitech.com",
    "mizuho global services": "https://www.mizuhogroup.com/asia-pacific/mizuho-global-services",
    "movate technologies": "https://www.movate.com/",
    "mphasis": "https://www.mphasis.com/",
    "myezcare": "https://www.myezcare.com/",
    "nagarro": "https://www.nagarro.com/",
    "national institute for smart government (nisg)": "http://www.nisg.org",
    "ndx financial services": "https://ndxfinserv.com/",
    "nec corporation": "https://in.nec.com/",
    "neogen chemicals": "https://neogenchem.com/",
    "netedge computing solutions": "https://www.netedgecomputing.com/",
    "neurealm": "https://www.neurealm.com/",
    "newt global": "https://www.newtglobal.com",
    "nielseniq india": "https://nielseniq.com/global/en/",
    "nokia": "https://www.nokia.com/",
    "nous infosystems": "https://www.nousinfosystems.com",
    "novel office": "https://www.noveloffice.in",
    "ntt data": "https://services.global.ntt/en-us/",
    "ntt data, inc.": "https://services.global.ntt/en-us/",
    "nvidia": "https://www.nvidia.com/",
    "nysa biomed": "https://nysabiomed.com/",
    "odessa": "https://www.odessainc.com/",
    "opentext": "https://www.opentext.com/",
    "optimum solutions": "https://theoptimum.net/",
    "oracle": "https://www.oracle.com/",
    "orange business services": "https://www.orange-business.com/en",
    "orion systems": "https://www.orioninc.com/",
    "osi digital": "https://www.osidigital.com/",
    "ovivo india": "https://www.ovivowater.com/en/",
    "p3 design solutions": "http://www.p3designsolutions.com/",
    "paradigm realty": "https://paradigmrealty.co.in/",
    "peakalpha": "https://www.peakalpha.com",
    "pearl": "https://www.pearl.com/careers",
    "perficient": "http://www.perficient.com",
    "persistent": "https://www.persistent.com/",
    "persistent systems": "https://www.persistent.com/",
    "photon": "http://www.photon.in/",
    "principal financial group": "https://www.principal.com/",
    "prodapt solutions": "https://www.prodapt.com/",
    "protiviti india": "https://www.protiviti.com/IN-en",
    "pwc": "https://www.pwc.com/",
    "pwc service delivery center": "https://www.pwc.com/",
    "qentelli": "http://www.qentelli.com",
    "qualcomm": "https://www.qualcomm.com/",
    "qualitykiosk technologies": "https://www.qualitykiosk.com/",
    "quest global": "https://www.quest-global.com/",
    "quick heal technologies": "https://www.quickheal.co.in/",
    "reliance": "https://www.ril.com/",
    "reliance industries": "https://www.ril.com/",
    "reliance jio": "https://www.jio.com/",
    "rf managed services": "https://www.realfoundations.in",
    "rg group (real estate, sec-67, noida)": "http://www.rgluxury.co.in",
    "ridik": "https://xtreemsolution.com/",
    "rigved technologies": "http://www.rigvedtech.com/",
    "rock solid solutions": "http://www.rocksolid.in/",
    "royaloak incorporation": "https://www.royaloakindia.com/",
    "sagility india": "https://sagility.com/",
    "salesforce": "https://www.salesforce.com/",
    "sap": "https://www.sap.com/",
    "sapiens": "https://www.sapiens.com",
    "siemens": "https://www.siemens.com/in/en.html",
    "sightspectrum": "http://www.sightspectrum.com",
    "simple energy": "https://www.simpleenergy.in/",
    "smart ims": "http://www.SmartIMS.com",
    "south asian foods corporation": "https://mrgolisoda.com/",
    "spekond": "https://www.spekond.com/",
    "srm technologies": "https://www.srmtech.com",
    "state street": "https://www.statestreet.com/home.html",
    "sutherland": "https://www.sutherlandglobal.com/",
    "svn systech india": "http://svnindia.com/",
    "synechron": "https://www.synechron.com/",
    "synergy computer solutions": "https://www.synergycom.com",
    "t-systems ict india pvt ltd": "https://www.t-systems.com/in/en",
    "taazaa tech": "https://www.taazaa.com/",
    "tanisha systems": "http://www.tanishasystems.com",
    "tanla platforms": "https://www.tanla.com/",
    "tata communications": "https://www.tatacommunications.com/",
    "tata consultancy services": "https://www.tcs.com/",
    "tata elxsi": "https://www.tataelxsi.com/",
    "tavant": "https://www.tavant.com/",
    "tcs": "https://www.tcs.com/",
    "tech mahindra": "https://www.techmahindra.com/",
    "tech smcsquared gcc": "https://www.smc2.com/",
    "techathalon software": "http://www.techathalon.com/",
    "technoidentity": "https://technoidentity.com/",
    "techstar group": "https://techstargroup.com/",
    "teksystems": "https://www.teksystems.com",
    "tekwissen": "https://www.tekwissen.com/",
    "teliolabs communication": "https://www.teliolabs.com/",
    "tenarai technologies private limited": "https://www.tenarai.com/",
    "thoucentric": "https://wwww.thoucentric.com",
    "tracxn": "https://tracxn.com/",
    "tranzeal": "https://www.tranzeal.com",
    "tronicszone": "https://www.tronicszone.com",
    "truminds": "http://www.truminds.com/",
    "unify technologies": "https://unifytech.com/",
    "valgenesis": "https://www.valgenesis.com/",
    "valuelabs": "https://www.valuelabs.com",
    "valuenable": "https://valuenable.in/",
    "vconstruct": "http://www.vconstruct.com",
    "vertisystem": "https://vertisystem.com/",
    "vijay sales": "https://www.vijaysales.com",
    "virtusa": "https://www.virtusa.com/",
    "visteon": "https://www.visteon.com/",
    "voya india": "https://www.voyaindia.com/",
    "vtechfamily solution india": "https://www.vtechsoln.in/",
    "webol": "https://webol.co.uk/",
    "wipro": "https://www.wipro.com/",
    "xoriant": "https://www.xoriant.com/",
    "yash technologies": "https://www.yash.com/",
    "zelis healthcare": "https://www.zelis.com/",
    "zensar": "https://www.zensar.com/",
    "zensar technologies": "https://www.zensar.com/",
}


def clean_html(text: Optional[str]) -> str:
    """Strip HTML tags and unescape entities into clean plain text."""
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    t = re.sub(r"</(p|li|h\d)>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


async def enrich_company_websites_in_browser(
    jobs: List[Dict[str, Any]],
    context: BrowserContext,
    num_tabs: int = 2,
    max_enrichment_seconds: float = 90.0,
) -> None:
    """Enrich jobs with official company websites:
    1. Instant lookup for known enterprise employers (0ms).
    2. Cached lookup for previous hits.
    3. Paced multi-tab live extraction for remaining companies.
    4. Guaranteed no-hang with hard timeouts and graceful cleanup.
    """
    url_to_comp: Dict[str, str] = {}
    for j in jobs:
        ab_url = j.get("ambition_box_url")
        cname = (j.get("company") or "").strip()
        if ab_url and ab_url.startswith("http") and ab_url not in url_to_comp:
            url_to_comp[ab_url] = cname or "Company"

    unique_items = list(url_to_comp.items())
    total = len(unique_items)
    if total == 0:
        return

    print(f"\n[*] Enriching {total} unique company websites...", flush=True)
    logger.info("Enriching %d unique company websites...", total)

    completed = 0
    url_to_website: Dict[str, str] = {}
    remaining_to_fetch: List[tuple[str, str]] = []

    # 1. Fast resolve known domains and cached items
    for ab_url, comp_name in unique_items:
        norm_name = comp_name.lower().strip()
        if ab_url in _COMPANY_WEBSITE_CACHE:
            url_to_website[ab_url] = _COMPANY_WEBSITE_CACHE[ab_url]
            completed += 1
        elif norm_name in KNOWN_COMPANY_DOMAINS:
            site = KNOWN_COMPANY_DOMAINS[norm_name]
            _COMPANY_WEBSITE_CACHE[ab_url] = site
            url_to_website[ab_url] = site
            completed += 1
            print(f"[{completed}/{total}] {comp_name} -> {site} (Known Registry)", flush=True)
        else:
            remaining_to_fetch.append((ab_url, comp_name))

    print(f"[+] Instantly resolved {completed}/{total} companies. Fetching remaining {len(remaining_to_fetch)} via live browser tabs...", flush=True)

    if not remaining_to_fetch:
        for job in jobs:
            ab_url = job.get("ambition_box_url", "")
            if ab_url in url_to_website:
                job["company_website"] = url_to_website[ab_url]
        return

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    for item in remaining_to_fetch:
        await queue.put(item)

    consecutive_blocks = 0

    async def worker_tab(tab_id: int) -> None:
        nonlocal completed, consecutive_blocks
        page: Optional[Page] = None
        try:
            page = await context.new_page()

            async def route_handler(route):
                try:
                    if route.request.resource_type in ["image", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()
                except Exception:
                    pass

            await page.route("**/*", route_handler)

            while not queue.empty():
                try:
                    ab_url, comp_name = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                # If Cloudflare anti-bot blocks multiple consecutive times, break early without hanging
                if consecutive_blocks >= 12:
                    _COMPANY_WEBSITE_CACHE[ab_url] = ""
                    url_to_website[ab_url] = ""
                    completed += 1
                    print(f"[{completed}/{total}] {comp_name} -> [Rate Limited]", flush=True)
                    queue.task_done()
                    continue

                website = ""
                try:
                    await page.goto(ab_url, wait_until="domcontentloaded", timeout=12000)
                    for _ in range(25):
                        html_text = await page.content()
                        if "__NEXT_DATA__" in html_text or '"website"' in html_text:
                            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text)
                            if m:
                                try:
                                    d = json.loads(m.group(1))
                                    props = d.get("props", {}).get("pageProps", {})
                                    meta = props.get("companyMetaInformation", {})
                                    header = props.get("companyHeaderData", {})
                                    website = (meta.get("website") or header.get("website") or "").strip()
                                except Exception:
                                    pass

                            if not website:
                                web_m = re.search(r'"website"\s*:\s*"(https?://[^"]+)"', html_text)
                                if web_m:
                                    website = web_m.group(1).replace("\\/", "").strip()

                            if website:
                                break
                        await asyncio.sleep(0.1)

                except Exception:
                    pass

                if website:
                    consecutive_blocks = 0
                else:
                    consecutive_blocks += 1

                _COMPANY_WEBSITE_CACHE[ab_url] = website
                url_to_website[ab_url] = website
                completed += 1

                display_web = website if website else "[Not listed]"
                print(f"[{completed}/{total}] {comp_name} -> {display_web}", flush=True)
                queue.task_done()
                # Pacing between calls to avoid triggering Cloudflare rate limits
                await asyncio.sleep(0.15)

        except Exception:
            pass
        finally:
            if page:
                try:
                    await page.unroute("**/*")
                    await asyncio.wait_for(page.close(), timeout=3.0)
                except Exception:
                    pass

    actual_tabs = min(num_tabs, len(remaining_to_fetch))
    try:
        await asyncio.wait_for(
            asyncio.gather(*(worker_tab(i) for i in range(actual_tabs))),
            timeout=max_enrichment_seconds,
        )
    except asyncio.TimeoutError:
        print(f"[!] Reached max enrichment time limit ({max_enrichment_seconds}s); proceeding with collected data.", flush=True)

    # Assign enriched websites back to all matching jobs
    found_count = 0
    for job in jobs:
        ab_url = job.get("ambition_box_url", "")
        if ab_url in url_to_website:
            web = url_to_website[ab_url]
            job["company_website"] = web
            if web:
                found_count += 1

    print(f"[+] Finished company website enrichment ({found_count}/{total} resolved).\n", flush=True)


class NaukriBrowserScraper:
    """High-performance parallel browser scraper for Naukri search URLs."""

    def __init__(self, headless: bool = True, timeout_ms: int = 35000, num_workers: int = 3) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.num_workers = max(1, num_workers)

    def _build_page_url(self, base_url: str, page_num: int) -> str:
        """Construct paginated URL for Naukri search."""
        if page_num <= 1:
            return base_url

        if "?" in base_url:
            path, query = base_url.split("?", 1)
            path = re.sub(r"-\d+$", "", path)
            return f"{path}-{page_num}?{query}"
        else:
            path = re.sub(r"-\d+$", "", base_url)
            return f"{path}-{page_num}"

    async def _scrape_tab_worker(
        self,
        worker_id: int,
        page_numbers: List[int],
        search_url: str,
        context: BrowserContext,
    ) -> List[Dict[str, Any]]:
        """Worker task to scrape a subset of pages on its own tab."""
        page: Page = await context.new_page()

        # Abort images and media for fast network performance
        async def route_handler(route):
            try:
                if route.request.resource_type in ["image", "media"]:
                    await route.abort()
                else:
                    await route.continue_()
            except Exception:
                pass

        await page.route("**/*", route_handler)

        # Single unified response listener for the lifetime of this page
        latest_page_jobs: List[Dict[str, Any]] = []

        async def on_res(response):
            if "jobapi/v3/search" in response.url or "jobapi" in response.url:
                try:
                    payload = await response.json()
                    jobs = payload.get("jobDetails", [])
                    if jobs:
                        latest_page_jobs.extend(jobs)
                except Exception:
                    pass

        page.on("response", on_res)

        worker_jobs: List[Dict[str, Any]] = []
        consecutive_empty = 0

        # Stagger initial launch slightly between workers
        await asyncio.sleep((worker_id - 1) * 0.4)

        for page_num in page_numbers:
            target_url = self._build_page_url(search_url, page_num)
            latest_page_jobs.clear()

            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                # Wait dynamically for API response payload
                for _ in range(60):
                    if latest_page_jobs:
                        break
                    await asyncio.sleep(0.1)

                if not latest_page_jobs:
                    try:
                        await page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=6000)
                    except Exception:
                        pass

            except Exception as exc:
                logger.debug("[Worker %d] Page %d timeout/exception: %s", worker_id, page_num, exc)

            if latest_page_jobs:
                consecutive_empty = 0
                for raw in latest_page_jobs:
                    job_id = str(raw.get("jobId") or "").strip()
                    if not job_id:
                        continue

                    ph_dict = {p.get("type"): p.get("label", "") for p in raw.get("placeholders", []) if isinstance(p, dict)}
                    title = raw.get("title", "").strip()
                    company = raw.get("companyName", "").strip()
                    location = ph_dict.get("location") or raw.get("location", "India")
                    exp_text = ph_dict.get("experience") or raw.get("experienceText", "Not specified")
                    salary = ph_dict.get("salary") or "Not disclosed"

                    raw_skills = raw.get("tagsAndSkills", "")
                    skills = ", ".join([str(s.get("label", s)) for s in raw_skills]) if isinstance(raw_skills, list) else str(raw_skills)

                    job_desc = clean_html(raw.get("jobDescription", ""))

                    ab_data = raw.get("ambitionBoxData") or {}
                    company_rating = str(ab_data.get("AggregateRating", "")).strip()
                    reviews_count = str(ab_data.get("ReviewsCount", "")).strip()
                    raw_ab_url = ab_data.get("Url", "")
                    ambition_box_url = ""
                    if raw_ab_url:
                        clean_ab = raw_ab_url.split("?")[0]
                        ambition_box_url = re.sub(
                            r"/reviews/([a-zA-Z0-9_-]+)-reviews",
                            r"/overview/\1-overview",
                            clean_ab,
                        )

                    vacancies = str(raw.get("vacancy", "")).strip()
                    freshness = raw.get("footerPlaceholderLabel", "").strip()

                    created_ts = raw.get("createdDate")
                    posted_date = ""
                    if created_ts:
                        try:
                            posted_date = datetime.datetime.fromtimestamp(created_ts / 1000.0).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    if not posted_date and len(job_id) >= 6:
                        parsed_tmp = parse_job_url(f"https://www.naukri.com/job-listings-{job_id}")
                        if parsed_tmp:
                            posted_date = parsed_tmp.get("posted_date", "")

                    min_exp = 0
                    max_exp = 99
                    try:
                        if raw.get("minimumExperience") is not None:
                            min_exp = int(raw["minimumExperience"])
                        if raw.get("maximumExperience") is not None:
                            max_exp = int(raw["maximumExperience"])
                    except (ValueError, TypeError):
                        pass

                    jd_url = raw.get("jdURL", "")
                    full_url = "https://www.naukri.com" + jd_url if jd_url and not jd_url.startswith("http") else jd_url

                    worker_jobs.append({
                        "job_id": job_id,
                        "title": title,
                        "company": company,
                        "company_website": "",
                        "location": location,
                        "experience_text": exp_text,
                        "salary": salary,
                        "skills": skills,
                        "job_description": job_desc,
                        "company_rating": company_rating,
                        "company_reviews_count": reviews_count,
                        "ambition_box_url": ambition_box_url,
                        "vacancies": vacancies,
                        "freshness": freshness,
                        "posted_date": posted_date,
                        "min_experience": min_exp,
                        "max_experience": max_exp,
                        "url": full_url,
                        "source": "naukri",
                    })

                logger.info("[Worker %d] Page %d scraped (%d jobs).", worker_id, page_num, len(latest_page_jobs))
            else:
                # Fallback to DOM elements if API response was missed
                cards = await page.query_selector_all(".srp-jobtuple-wrapper, .cust-job-tuple")
                if not cards:
                    consecutive_empty += 1
                    if consecutive_empty >= 2:
                        logger.info("[Worker %d] Reached end of results at page %d; stopping worker.", worker_id, page_num)
                        break
                    continue

                consecutive_empty = 0
                for card in cards:
                    try:
                        title_el = await card.query_selector("a.title")
                        if not title_el:
                            continue
                        job_url = (await title_el.get_attribute("href")) or ""
                        parsed = parse_job_url(job_url)
                        job_id = parsed["job_id"] if parsed else str(abs(hash(job_url)))

                        comp_el = await card.query_selector("a.comp-name, a.company, .comp-name")
                        exp_el = await card.query_selector(".expwdth, .exp-wrap, span[class*='exp']")
                        sal_el = await card.query_selector(".sal-wrap, span[class*='sal']")
                        loc_el = await card.query_selector(".loc-wrap, span[class*='loc']")
                        desc_el = await card.query_selector(".job-desc, .job-description, .dang-inner-html")
                        rating_el = await card.query_selector(".rating, span[class*='rating']")
                        reviews_el = await card.query_selector(".review, span[class*='review']")

                        tag_els = await card.query_selector_all("ul.tags-gt li, .tag-li")
                        dom_skills = ", ".join([(await t.inner_text()).strip() for t in tag_els if (await t.inner_text()).strip()])

                        worker_jobs.append({
                            "job_id": job_id,
                            "title": (await title_el.inner_text()).strip(),
                            "company": (await comp_el.inner_text()).strip() if comp_el else "",
                            "company_website": "",
                            "location": (await loc_el.inner_text()).strip() if loc_el else "India",
                            "experience_text": (await exp_el.inner_text()).strip() if exp_el else "Not specified",
                            "salary": (await sal_el.inner_text()).strip() if sal_el else "Not disclosed",
                            "skills": dom_skills,
                            "job_description": clean_html(await desc_el.inner_text()) if desc_el else "",
                            "company_rating": (await rating_el.inner_text()).strip() if rating_el else "",
                            "company_reviews_count": (await reviews_el.inner_text()).strip() if reviews_el else "",
                            "ambition_box_url": "",
                            "vacancies": "",
                            "freshness": "",
                            "posted_date": parsed["posted_date"] if parsed else "",
                            "min_experience": parsed["min_experience"] if parsed else 0,
                            "max_experience": parsed["max_experience"] if parsed else 99,
                            "url": job_url,
                            "source": "naukri",
                        })
                    except Exception:
                        continue

        try:
            await page.unroute("**/*")
            await asyncio.wait_for(page.close(), timeout=3.0)
        except Exception:
            pass

        return worker_jobs

    async def _async_scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Internal asynchronous multi-tab coordinator."""
        async with async_playwright() as p:
            browser: Optional[Browser] = None
            for channel in ["msedge", "chrome", None]:
                try:
                    kwargs: Dict[str, Any] = {
                        "headless": self.headless,
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-setuid-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-gpu",
                        ],
                    }
                    if channel:
                        kwargs["channel"] = channel
                    browser = await p.chromium.launch(**kwargs)
                    break
                except Exception:
                    continue

            if not browser:
                logger.error("Could not launch Playwright browser. Please ensure browsers are installed (`playwright install`).")
                return []

            context: BrowserContext = await browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Asia/Kolkata",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                },
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            # Partition pages among workers (interleaved for load balancing)
            actual_workers = min(self.num_workers, max_pages)
            all_page_nums = list(range(1, max_pages + 1))
            worker_partitions = [all_page_nums[i::actual_workers] for i in range(actual_workers)]

            tasks = [
                self._scrape_tab_worker(w_idx + 1, parts, search_url, context)
                for w_idx, parts in enumerate(worker_partitions)
            ]

            results = await asyncio.gather(*tasks)

            # Deduplicate and cap results
            all_jobs: List[Dict[str, Any]] = []
            seen_job_ids: Set[str] = set()

            for worker_res in results:
                for job in worker_res:
                    jid = job.get("job_id")
                    if jid and jid not in seen_job_ids:
                        seen_job_ids.add(jid)
                        all_jobs.append(job)
                        if len(all_jobs) >= max_jobs:
                            break
                if len(all_jobs) >= max_jobs:
                    break

            # Enrich company websites inside the active browser context with live terminal logging
            await enrich_company_websites_in_browser(all_jobs, context, num_tabs=2, max_enrichment_seconds=90.0)

            try:
                await asyncio.wait_for(browser.close(), timeout=5.0)
            except Exception:
                pass

        logger.info("Scraped %d unique jobs across %d pages.", len(all_jobs), max_pages)
        return all_jobs

    def scrape_url(
        self,
        search_url: str,
        max_pages: int = 5,
        max_jobs: int = 100,
    ) -> List[Dict[str, Any]]:
        """Synchronous public entry point for CLI and external callers."""
        try:
            return asyncio.run(self._async_scrape_url(search_url, max_pages, max_jobs))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._async_scrape_url(search_url, max_pages, max_jobs))
