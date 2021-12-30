"""Support to manage a check list."""
from http import HTTPStatus
import logging
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import http, websocket_api
from homeassistant.components.http.data_validator import RequestDataValidator
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.util.json import load_json, save_json

from .const import DOMAIN

ATTR_NAME = "name"
ATTR_TYPE = "type"
ATTR_COMPLETE = "complete"

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = vol.Schema({DOMAIN: {}}, extra=vol.ALLOW_EXTRA)
EVENT = "check_list_updated"
ITEM_UPDATE_SCHEMA = vol.Schema({ATTR_COMPLETE: bool, ATTR_NAME: str, ATTR_TYPE: str})
PERSISTENCE = ".check_list.json"

SERVICE_ADD_ITEM = "add_item"
SERVICE_COMPLETE_ITEM = "complete_item"
SERVICE_LIST_ITEMS = "list_items"
SERVICE_CLEAR_COMPLETE = "clear_complete"
SERVICE_INCOMPLETE_ITEM = "incomplete_item"
SERVICE_COMPLETE_ALL = "complete_all"
SERVICE_INCOMPLETE_ALL = "incomplete_all"
SERVICE_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): vol.Any(None, cv.string),
        vol.Optional(ATTR_TYPE): vol.Any(None, cv.string),
    }
)
SERVICE_LIST_SCHEMA = vol.Schema({})

WS_TYPE_SHOPPING_LIST_ITEMS = "check_list/items"
WS_TYPE_SHOPPING_LIST_ADD_ITEM = "check_list/items/add"
WS_TYPE_SHOPPING_LIST_UPDATE_ITEM = "check_list/items/update"
WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS = "check_list/items/clear"

SCHEMA_WEBSOCKET_ITEMS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_ITEMS}
)

SCHEMA_WEBSOCKET_ADD_ITEM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_ADD_ITEM, vol.Required("name"): str}
)

SCHEMA_WEBSOCKET_UPDATE_ITEM = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_SHOPPING_LIST_UPDATE_ITEM,
        vol.Required("item_id"): str,
        vol.Optional("name"): str,
        vol.Optional("complete"): bool,
    }
)

SCHEMA_WEBSOCKET_CLEAR_ITEMS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS}
)


async def async_setup(hass, config):
    """Initialize the check list."""

    if DOMAIN not in config:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}
        )
    )

    return True


async def async_setup_entry(hass, config_entry):
    """Set up check list from config flow."""

    async def add_item_service(call):
        """Add an item with `name`."""
        data = hass.data[DOMAIN]
        name = call.data.get(ATTR_NAME)
        type = call.data.get(ATTR_TYPE)
        if name is not None:
            await data.async_add(name, type)

    async def complete_item_service(call):
        """Mark the item provided via `name` as completed."""
        data = hass.data[DOMAIN]
        name = call.data.get(ATTR_NAME)
        type = call.data.get(ATTR_TYPE)
        if name is None:
            return
        try:
            item = [item for item in data.items if item["name"] == name][0]
        except IndexError:
            _LOGGER.error("Removing of item failed: %s cannot be found", name)
        else:
            await data.async_update(
                item["id"], {"name": name, "type": type, "complete": True}
            )

    async def clear_complete_service(call):
        """Handle clearing check_list items."""
        await data.async_clear_completed()

    async def list_items_service(call):
        await data.async_list_items()

    async def incomplete_item_service(call):
        """Mark the item provided via `name` as incomplete."""
        data = hass.data[DOMAIN]
        name = call.data.get(ATTR_NAME)
        type = call.data.get(ATTR_TYPE)
        if name is None:
            return
        try:
            item = [item for item in data.items if item["name"] == name][0]
        except IndexError:
            _LOGGER.error("Restoring of item failed: %s cannot be found", name)
        else:
            await data.async_update(
                item["id"], {"name": name, "type": type, "complete": False}
            )

    async def complete_all_service(call):
        """Mark all items in the list as complete."""
        await data.async_update_list({"complete": True})

    async def incomplete_all_service(call):
        """Mark all items in the list as incomplete."""
        await data.async_update_list({"complete": False})

    data = hass.data[DOMAIN] = CheckData(hass)
    await data.async_load()

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_ITEM, add_item_service, schema=SERVICE_ITEM_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_ITEM, complete_item_service, schema=SERVICE_ITEM_SCHEMA
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_COMPLETE,
        clear_complete_service,
        schema=SERVICE_LIST_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_ITEMS,
        list_items_service,
        schema=SERVICE_LIST_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_INCOMPLETE_ITEM,
        incomplete_item_service,
        schema=SERVICE_ITEM_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_COMPLETE_ALL,
        complete_all_service,
        schema=SERVICE_LIST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_INCOMPLETE_ALL,
        incomplete_all_service,
        schema=SERVICE_LIST_SCHEMA,
    )

    hass.http.register_view(CheckListView)
    hass.http.register_view(CreateCheckListItemView)
    hass.http.register_view(UpdateCheckListItemView)
    hass.http.register_view(ClearCompletedItemsView)

    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_ITEMS, websocket_handle_items, SCHEMA_WEBSOCKET_ITEMS
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_ADD_ITEM, websocket_handle_add, SCHEMA_WEBSOCKET_ADD_ITEM
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_UPDATE_ITEM,
        websocket_handle_update,
        SCHEMA_WEBSOCKET_UPDATE_ITEM,
    )
    hass.components.websocket_api.async_register_command(
        WS_TYPE_SHOPPING_LIST_CLEAR_ITEMS,
        websocket_handle_clear,
        SCHEMA_WEBSOCKET_CLEAR_ITEMS,
    )

    websocket_api.async_register_command(hass, websocket_handle_reorder)

    return True


class CheckData:
    """Class to hold check list data."""

    def __init__(self, hass):
        """Initialize the check list."""
        self.hass = hass
        self.items = []

    async def async_add(self, name, type):
        """Add a check list item."""
        item = {
            "name": name,
            "type": type,
            "id": uuid.uuid4().hex,
            "complete": False,
            "index": len(self.items),
        }
        self.items.append(item)
        await self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(EVENT, {"action": "add", "item": item})
        return item

    async def async_update(self, item_id, info):
        """Update a check list item."""
        item = next((itm for itm in self.items if itm["id"] == item_id), None)

        if item is None:
            raise KeyError

        info = ITEM_UPDATE_SCHEMA(info)
        item.update(info)
        await self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(EVENT, {"action": "update", "item": item})
        return item

    async def async_clear_completed(self):
        """Clear completed items."""
        self.items = [itm for itm in self.items if not itm["complete"]]
        await self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(
            EVENT, {"action": "clear_completed", "items": self.items}
        )

    async def async_list_items(self):
        await self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(EVENT, {"action": "list_items", "items": self.items})
        return self.items

    async def async_update_list(self, info):
        """Update all items in the list."""
        for item in self.items:
            item.update(info)
        await self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(EVENT, {"action": "update_list", "items": self.items})
        return self.items

    @callback
    def async_reorder(self, item_ids):
        """Reorder items."""
        # The array for sorted items.
        new_items = []
        all_items_mapping = {item["id"]: item for item in self.items}
        # Append items by the order of passed in array.
        for item_id in item_ids:
            if item_id not in all_items_mapping:
                raise KeyError
            new_items.append(all_items_mapping[item_id])
            # Remove the item from mapping after it's appended in the result array.
            del all_items_mapping[item_id]
        # Append the rest of the items
        for key in all_items_mapping:
            # All the unchecked items must be passed in the item_ids array,
            # so all items left in the mapping should be checked items.
            if all_items_mapping[key]["complete"] is False:
                raise vol.Invalid(
                    "The item ids array doesn't contain all the unchecked check list items."
                )
            new_items.append(all_items_mapping[key])
        self.items = new_items
        self.hass.async_add_executor_job(self.save)
        self.hass.bus.async_fire(EVENT, {"action": "reorder", "items": self.items})

    async def async_load(self):
        """Load items."""

        def load():
            """Load the items synchronously."""
            return load_json(self.hass.config.path(PERSISTENCE), default=[])

        self.items = await self.hass.async_add_executor_job(load)

    def save(self):
        """Save the items."""
        save_json(self.hass.config.path(PERSISTENCE), self.items)


class CheckListView(http.HomeAssistantView):
    """View to retrieve check list content."""

    url = "/api/check_list"
    name = "api:check_list"

    @callback
    def get(self, request):
        """Retrieve check list items."""
        return self.json(request.app["hass"].data[DOMAIN].items)


class UpdateCheckListItemView(http.HomeAssistantView):
    """View to retrieve check list content."""

    url = "/api/check_list/item/{item_id}"
    name = "api:check_list:item:id"

    async def post(self, request, item_id):
        """Update a check list item."""
        data = await request.json()

        try:
            item = await request.app["hass"].data[DOMAIN].async_update(item_id, data)
            request.app["hass"].bus.async_fire(EVENT)
            return self.json(item)
        except KeyError:
            return self.json_message("Item not found", HTTPStatus.NOT_FOUND)
        except vol.Invalid:
            return self.json_message("Item not found", HTTPStatus.BAD_REQUEST)


class CreateCheckListItemView(http.HomeAssistantView):
    """View to retrieve check list content."""

    url = "/api/check_list/item"
    name = "api:check_list:item"

    @RequestDataValidator(vol.Schema({vol.Required("name"): str}))
    async def post(self, request, data):
        """Create a new check list item."""
        item = (
            await request.app["hass"].data[DOMAIN].async_add(data["name"], data["type"])
        )
        request.app["hass"].bus.async_fire(EVENT)
        return self.json(item)


class ClearCompletedItemsView(http.HomeAssistantView):
    """View to retrieve check list content."""

    url = "/api/check_list/clear_completed"
    name = "api:check_list:clear_completed"

    async def post(self, request):
        """Retrieve if API is running."""
        hass = request.app["hass"]
        await hass.data[DOMAIN].async_clear_completed()
        hass.bus.async_fire(EVENT)
        return self.json_message("Cleared completed items.")


@callback
def websocket_handle_items(hass, connection, msg):
    """Handle get check_list items."""
    connection.send_message(
        websocket_api.result_message(msg["id"], hass.data[DOMAIN].items)
    )


@websocket_api.async_response
async def websocket_handle_add(hass, connection, msg):
    """Handle add item to check_list."""
    item = await hass.data[DOMAIN].async_add(msg["name"], msg["type"])
    hass.bus.async_fire(EVENT, {"action": "add", "item": item})
    connection.send_message(websocket_api.result_message(msg["id"], item))


@websocket_api.async_response
async def websocket_handle_update(hass, connection, msg):
    """Handle update check_list item."""
    msg_id = msg.pop("id")
    item_id = msg.pop("item_id")
    msg.pop("type")
    data = msg

    try:
        item = await hass.data[DOMAIN].async_update(item_id, data)
        hass.bus.async_fire(EVENT, {"action": "update", "item": item})
        connection.send_message(websocket_api.result_message(msg_id, item))
    except KeyError:
        connection.send_message(
            websocket_api.error_message(msg_id, "item_not_found", "Item not found")
        )


@websocket_api.async_response
async def websocket_handle_clear(hass, connection, msg):
    """Handle clearing check_list items."""
    await hass.data[DOMAIN].async_clear_completed()
    hass.bus.async_fire(EVENT, {"action": "clear", "items": hass.data[DOMAIN].items})
    connection.send_message(websocket_api.result_message(msg["id"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "check_list/items/reorder",
        vol.Required("item_ids"): [str],
    }
)
def websocket_handle_reorder(hass, connection, msg):
    """Handle reordering check_list items."""
    msg_id = msg.pop("id")
    try:
        hass.data[DOMAIN].async_reorder(msg.pop("item_ids"))
        hass.bus.async_fire(EVENT, {"action": "reorder"})
        connection.send_result(msg_id)
    except KeyError:
        connection.send_error(
            msg_id,
            websocket_api.const.ERR_NOT_FOUND,
            "One or more item id(s) not found.",
        )
    except vol.Invalid as err:
        connection.send_error(msg_id, websocket_api.const.ERR_INVALID_FORMAT, f"{err}")
