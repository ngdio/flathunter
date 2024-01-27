"""Expose crawler for ImmoWelt"""
import re
import datetime
import hashlib
import json

from bs4 import BeautifulSoup, Tag
from jsonpath_ng.ext import parse

from flathunter.logging import logger
from flathunter.abstract_crawler import Crawler

class Immowelt(Crawler):
    """Implementation of Crawler interface for ImmoWelt"""

    URL_PATTERN = re.compile(r'https://www\.immowelt\.de')

    JSON_PATH_PARSER_ENTRIES = parse("$..estateSearch.data.estates[*]")
    JSON_PATH_PARSER_IMAGES = parse("$.pictures..imageUri")
    JSON_PATH_PARSER_COLD_RENT = parse("$.prices[?'type'=='COLD_RENT'].amountMin")
    JSON_PATH_PARSER_WARM_RENT = parse("$.prices[?'type'=='RENT_INCLUDING_HEATING'].amountMin")
    JSON_PATH_PARSER_AREA = parse("$.areas[?'type'=='LIVING_AREA'].sizeMin")

    # Using Immoscout fallback as Immowelt supplies a SVG file as fallback
    FALLBACK_IMAGE_URL = "https://www.static-immobilienscout24.de/statpic/placeholder_house/" + \
                         "496c95154de31a357afa978cdb7f15f0_placeholder_medium.png"

    def __init__(self, config):
        super().__init__(config)
        self.config = config

    def get_entries_from_json(self, soup: BeautifulSoup):
        """Get entries from embedded JSON"""
        result_json = soup.find("script", attrs={"data-hypernova-key": "searchui"})
        if not result_json:
            return None

        result_dict = json.loads(result_json.string[4:-3])

        entries = [
            self.extract_entry_from_json(entry.value)
                for entry in self.JSON_PATH_PARSER_ENTRIES.find(result_dict)
        ]

        logger.debug('Number of found entries: %d', len(entries))
        return entries

    def process_id(self, hash):
        """Convert id from hash to numeric state"""
        return int(hashlib.sha256(hash.encode('utf-8')).hexdigest(), 16) % 10**16

    def extract_entry_from_json(self, entry):
        """Extract expose from single JSON entry"""
        entry_id = entry.get("onlineId", "0")
        processed_id = self.process_id(entry_id)

        images = [
            image.value for image in self.JSON_PATH_PARSER_IMAGES.find(entry)]

        place = entry.get("place", {})
        city = place.get("city", "").strip()
        if place.get("postcode"):
            city = f"{place['postcode']} {city}"
        district = place.get("district", "").strip()
        street = place.get("street", "").strip()
        address = ', '.join(
            filter(None,[street, district, city]))

        cold_rent = self.JSON_PATH_PARSER_COLD_RENT.find(entry)
        warm_rent = self.JSON_PATH_PARSER_WARM_RENT.find(entry)
        area = self.JSON_PATH_PARSER_AREA.find(entry)

        return {
            'id': processed_id,
            'url': f"https://www.immowelt.de/expose/{entry_id}",
            'image': images[0] if len(images) else self.FALLBACK_IMAGE_URL,
            'images': images,
            'title': entry.get("title", ''),
            'address': address or "N/A",
            'crawler': self.get_name(),
            'price': str(cold_rent[0].value) if cold_rent else '',
            'total_price': str(warm_rent[0].value) if warm_rent else '',
            'size': str(area[0].value) if area else '',
            'rooms': str(entry.get("roomsMin", ''))
        }

    def get_expose_details(self, expose):
        """Loads additional details for an expose by processing the expose detail URL"""
        soup = self.get_page(expose['url'])
        date = datetime.datetime.now().strftime("%2d.%2m.%Y")
        expose['from'] = date

        immo_div = soup.find("app-estate-object-informations")
        if not isinstance(immo_div, Tag):
            return expose
        immo_div = soup.find("div", {"class": "equipment ng-star-inserted"})
        if not isinstance(immo_div, Tag):
            return expose

        details = immo_div.find_all("p")
        for detail in details:
            if detail.text.strip() == "Bezug":
                date = detail.findNext("p").text.strip()
                no_exact_date_given = re.match(
                    r'.*sofort.*|.*Nach Vereinbarung.*',
                    date,
                    re.MULTILINE|re.DOTALL|re.IGNORECASE
                )
                if no_exact_date_given:
                    date = datetime.datetime.now().strftime("%2d.%2m.%Y")
                break
        expose['from'] = date
        return expose

    # pylint: disable=too-many-locals
    def extract_data(self, soup: BeautifulSoup):
        """Extracts all exposes from a provided Soup object"""
        json_results = self.get_entries_from_json(soup)
        if json_results:
            return json_results

        entries = []
        soup_res = soup.find("main")
        if not isinstance(soup_res, Tag):
            return []

        title_elements = soup_res.find_all("h2")
        expose_ids = soup_res.find_all("a", id=True)

        for idx, title_el in enumerate(title_elements):
            try:
                price = expose_ids[idx].find(
                    "div", attrs={"data-test": "price"}).text
            except IndexError:
                price = ""

            try:
                size = expose_ids[idx].find(
                    "div", attrs={"data-test": "area"}).text
            except IndexError:
                size = ""

            try:
                rooms = expose_ids[idx].find(
                    "div", attrs={"data-test": "rooms"}).text
            except IndexError:
                rooms = ""

            try:
                url = expose_ids[idx].get("href")
            except IndexError:
                continue

            picture = expose_ids[idx].find("picture")
            image = None
            if picture:
                src = picture.find("source")
                if src:
                    image = src.get("data-srcset")

            try:
                address = expose_ids[idx].find(
                    "div", attrs={"class": re.compile("IconFact.*")}
                  )
                address = address.find("span").text
            except (IndexError, AttributeError):
                address = ""

            processed_id = self.process_id(expose_ids[idx].get("id"))

            details = {
                'id': processed_id,
                'image': image,
                'url': url,
                'title': title_el.text.strip(),
                'rooms': rooms,
                'price': price,
                'size': size,
                'address': address,
                'crawler': self.get_name()
            }
            entries.append(details)

        logger.debug('Number of entries found: %d', len(entries))

        return entries
