# HA-Check-List
This is a quick and dirty custom implementation of the HA shopping list integration.  I am using this to increment through a list while checking off items as it goes.

This is untested so use at your own risk.

## Differences from Shopping List integration ##

There is no UI interface with this implementation. It work entirely in the background.

### Services ###

I have added two new services:

**clear_complete:** This will remove all items marked as completed.
**list_items:** This will send the entire list contents to the event bus.
