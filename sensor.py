
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
    async_add_entities([FortumSpotPriceSensor(coordinator)], True)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up via UI (future config flow)."""
    coordinator = SpotPriceCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([FortumSpotPriceSensor(coordinator)], True)


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
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

            try:
                series = data[0]["result"]["data"]["json"][0]["spotPriceSeries"]
            except Exception as e:
                _LOGGER.error("Failed to parse Fortum API response: %s", e)
                return {}

            # Map atUTC → total price (c/kWh)
            prices = {p["atUTC"]: p["spotPrice"]["total"] for p in series}
            return prices


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
        now_utc = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        now_hour_utc = now_utc.strftime("%Y-%m-%dT%H:00:00.000Z")
        return self.coordinator.data.get(now_hour_utc)

    @property
    def extra_state_attributes(self):
        """Expose all hourly prices and sorted hours as attributes."""
        attrs = dict(self.coordinator.data) if self.coordinator.data else {}
        # Build sorted list of (hour, price) tuples
        if self.coordinator.data:
            sorted_hours = sorted(self.coordinator.data.items(), key=lambda x: x[1])
            # Format as list of dicts for easy templating
            attrs["sorted_hours"] = [
                {"hour": hour, "price": price} for hour, price in sorted_hours
            ]
        else:
            attrs["sorted_hours"] = []
        return attrs
