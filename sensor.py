import datetime
import json
import logging
from urllib.parse import urlencode
import statistics

import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (CoordinatorEntity, DataUpdateCoordinator)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up via YAML (legacy)."""
    coordinator = SpotPriceCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([
        FortumSpotPrice15minSensor(coordinator),
        FortumSpotPrice15minRankSensor(coordinator),
        FortumSpotPriceHourSensor(coordinator),
        FortumSpotPriceHourRankSensor(coordinator)
    ], True)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up via UI (future config flow)."""
    coordinator = SpotPriceCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([
        FortumSpotPrice15minSensor(coordinator),
        FortumSpotPrice15minRankSensor(coordinator),
        FortumSpotPriceHourSensor(coordinator),
        FortumSpotPriceHourRankSensor(coordinator)
    ], True)

class SpotPriceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass):
        super().__init__(
            hass,
            _LOGGER,
            name="fortum_fi_spot_price",
            update_interval=datetime.timedelta(minutes=1),
        )
        self._last_fetched_date = None
        self._last_data = {}

    def build_api_url(self, date: str, price_area: str = "FI", resolution: str = "PER_15_MIN") -> str:
        base_url = "https://www.fortum.com/fi/sahkoa/api/trpc/shared.spotPrices.listPriceAreaSpotPrices"
        input_dict = {
            "0": {
                "json": {
                    "priceArea": price_area,
                    "fromDate": date,
                    "toDate": date,
                    "resolution": resolution,
                }
            }
        }

        input_json = json.dumps(input_dict, separators=(",", ":"))
        params = {
            "batch": 1,
            "input": input_json,
        }
        return f"{base_url}?{urlencode(params)}"


    async def _async_update_data(self):
        today = datetime.date.today().isoformat()
        if self._last_fetched_date == today and self._last_data:
            return self._last_data

        max_retries = 3
        prices_by_resolution = {}
        for resolution in ("PER_15_MIN", "HOUR"):
            url = self.build_api_url(today, resolution=resolution)
            for attempt in range(1, max_retries + 1):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status != 200:
                                _LOGGER.error(f"Fortum API request failed (status %s): %s", resp.status, url)
                                continue
                            try:
                                data = await resp.json()
                            except Exception as e:
                                _LOGGER.error("Failed to decode JSON from Fortum API: %s", e)
                                continue

                    try:
                        series = data[0]["result"]["data"]["json"][0]["spotPriceSeries"]
                    except (KeyError, IndexError, TypeError) as e:
                        _LOGGER.error("Unexpected Fortum API response structure: %s", e)
                        continue

                    try:
                        prices_by_resolution[resolution] = {
                            p["atUTC"]: p["spotPrice"]["total"] for p in series
                        }
                    except Exception as e:
                        _LOGGER.error("Failed to parse spot price series: %s", e)
                        continue
                    break
                except Exception as e:
                    _LOGGER.error("Error fetching Fortum spot prices (attempt %d/%d): %s", attempt, max_retries, e)

            if resolution not in prices_by_resolution:
                _LOGGER.error("All attempts to fetch %s Fortum spot prices failed.", resolution)
                return {}

        self._last_fetched_date = today
        self._last_data = prices_by_resolution
        return prices_by_resolution


class FortumSpotPrice15minSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current 15min's spot price."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price 15min"
        self._attr_unique_id = "fortum_fi_spot_price_15min"
        self._data_key = "PER_15_MIN"
        self._interval_minutes = 15

    @property
    def native_unit_of_measurement(self):
        return "c/kWh"

    @property
    def native_value(self):
        # Get current UTC time rounded down to the last 15min, format to match atUTC keys
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        minute = now_utc.minute - (now_utc.minute % self._interval_minutes)
        now_utc = now_utc.replace(minute=minute)
        interval_utc = now_utc.strftime("%Y-%m-%dT%H:%M:00.000Z")
        return self.coordinator.data.get(self._data_key, {}).get(interval_utc)

    @property
    def extra_state_attributes(self):
        attrs = {
            "min": None,
            "max": None,
            "median": None
        }
        data = self.coordinator.data.get(self._data_key, {})
        if data:
            prices = list(data.values())
            attrs["min"] = min(prices) if prices else None
            attrs["max"] = max(prices) if prices else None
            attrs["median"] = statistics.median(prices) if prices else None

        return attrs

    @property
    def icon(self):
        return "mdi:currency-eur"

class FortumSpotPrice15minRankSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current 15min's price rank (nth cheapest 15min)."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price Rank 15min"
        self._attr_unique_id = "fortum_fi_spot_price_rank_15min"

    @property
    def native_unit_of_measurement(self):
        return None

    @property
    def native_value(self):
        # Get current UTC time rounded down to the last 15min, format to match atUTC keys
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(second=0, microsecond=0)
        minute = now_utc.minute - (now_utc.minute % self._interval_minutes)
        now_utc = now_utc.replace(minute=minute)
        interval_utc = now_utc.strftime("%Y-%m-%dT%H:%M:00.000Z")
        data = self.coordinator.data.get(self._data_key, {})
        if not data or interval_utc not in data:
            return None

        sorted_time_intervals = sorted(data.items(), key=lambda x: x[1])
        time_to_price_rank = {time: price_rank for price_rank, (time, price) in enumerate(sorted_time_intervals)}
        return time_to_price_rank.get(interval_utc)

    @property
    def extra_state_attributes(self):
        return {}

    @property
    def icon(self):
        return "mdi:lightbulb-multiple-outline"


class FortumSpotPriceHourSensor(FortumSpotPrice15minSensor):
    """Sensor for the current hour's spot price."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price Hour"
        self._attr_unique_id = "fortum_fi_spot_price_hour"
        self._data_key = "HOUR"
        self._interval_minutes = 60


class FortumSpotPriceHourRankSensor(FortumSpotPrice15minRankSensor):
    """Sensor for the current hour's price rank."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price Rank Hour"
        self._attr_unique_id = "fortum_fi_spot_price_rank_hour"
        self._data_key = "HOUR"
        self._interval_minutes = 60

