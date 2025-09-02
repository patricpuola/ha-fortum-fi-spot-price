
import datetime
import json
import logging
from urllib.parse import urlencode

import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (CoordinatorEntity, DataUpdateCoordinator)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up via YAML (legacy)."""
    coordinator = SpotPriceCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([
        FortumSpotPriceSensor(coordinator),
        FortumSpotPriceRankSensor(coordinator)
    ], True)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up via UI (future config flow)."""
    coordinator = SpotPriceCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([
        FortumSpotPriceSensor(coordinator),
        FortumSpotPriceRankSensor(coordinator)
    ], True)
    
class FortumSpotPriceRankSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current hour's price rank (nth cheapest hour)."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price Rank"
        self._attr_unique_id = "fortum_fi_spot_price_rank"

    @property
    def native_unit_of_measurement(self):
        return None

    @property
    def native_value(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
        now_hour_utc = now_utc.strftime("%Y-%m-%dT%H:00:00.000Z")
        data = self.coordinator.data
        if not data or now_hour_utc not in data:
            return None
        
        sorted_hours = sorted(data.items(), key=lambda x: x[1])
        hour_to_price_rank = {hour: price_rank for price_rank, (hour, price) in enumerate(sorted_hours)}
        return hour_to_price_rank.get(now_hour_utc)

    @property
    def extra_state_attributes(self):
        return {}


class SpotPriceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass):
        super().__init__(
            hass,
            _LOGGER,
            name="fortum_fi_spot_price",
            update_interval=datetime.timedelta(minutes=30),
        )

    def build_api_url(self, date: str, price_area: str = "FI", resolution: str = "HOUR") -> str:
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
        url = self.build_api_url(today)
        max_retries = 3
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

                # Map atUTC → total price (c/kWh)
                try:
                    prices = {p["atUTC"]: p["spotPrice"]["total"] for p in series}
                except Exception as e:
                    _LOGGER.error("Failed to parse spot price series: %s", e)
                    continue
                return prices
            except Exception as e:
                _LOGGER.error("Error fetching Fortum spot prices (attempt %d/%d): %s", attempt, max_retries, e)
        _LOGGER.error("All attempts to fetch Fortum spot prices failed.")
        return {}


class FortumSpotPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current hour's spot price."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum FI Spot Price"
        self._attr_unique_id = "fortum_fi_spot_price"

    @property
    def native_unit_of_measurement(self):
        return "c/kWh"

    @property
    def native_value(self):
        # Get current UTC time rounded down to the hour, format to match atUTC keys
        now_utc = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
        now_hour_utc = now_utc.strftime("%Y-%m-%dT%H:00:00.000Z")
        return self.coordinator.data.get(now_hour_utc)

    @property
    def extra_state_attributes(self):
        attrs = { "forecast": [] }
        
        if self.coordinator.data:
            forecast = [
                {"datetime": hour, "value": price}
                for hour, price in sorted(self.coordinator.data.items())
            ]
            attrs["forecast"] = forecast
        return attrs
