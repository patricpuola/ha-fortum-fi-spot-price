import aiohttp
import datetime
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

API_URL = (
    "https://www.fortum.com/fi/sahkoa/api/trpc/shared.spotPrices.listPriceAreaSpotPrices"
    "?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B"
    "%22priceArea%22%3A%22FI%22,"
    "%22fromDate%22%3A%22{date}%22,"
    "%22toDate%22%3A%22{date}%22,"
    "%22resolution%22%3A%22HOUR%22%7D%7D%7D"
)


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
            name="fortum_spotprice",
            update_interval=datetime.timedelta(minutes=30),
        )

    async def _async_update_data(self):
        today = datetime.date.today().isoformat()
        url = API_URL.format(date=today)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        try:
            series = data[0]["result"]["data"]["json"][0]["spotPriceSeries"]
        except Exception as e:
            _LOGGER.error("Failed to parse Fortum API response: %s", e)
            return {}

        # Map atLocal → total price (c/kWh)
        prices = {p["atLocal"]: p["spotPrice"]["total"] for p in series}
        return prices


class FortumSpotPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for the current hour's spot price."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Fortum Spot Price"
        self._attr_unique_id = "fortum_spotprice"

    @property
    def native_unit_of_measurement(self):
        return "c/kWh"

    @property
    def native_value(self):
        now_hour = datetime.datetime.now().strftime("%Y-%m-%dT%H:00:00.000+03:00")
        return self.coordinator.data.get(now_hour)

    @property
    def extra_state_attributes(self):
        """Expose all hourly prices as attributes."""
        return self.coordinator.data
