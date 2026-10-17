# BKW Smart Meter for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-18BCF2.svg?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](custom_components/bkw/manifest.json)
[![IoT class](https://img.shields.io/badge/IoT%20class-cloud%20polling-lightgrey.svg)](https://developers.home-assistant.io/docs/creating_integration_manifest/#iot-class)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Imports the consumption of a BKW smart meter from [myBKW](https://my.bkw.ch) into
Home Assistant's long-term statistics, together with its cost, for the Energy
dashboard.

BKW publishes a day's 15-minute readings some time the next day, so the
statistics are always a day behind. For live values, the meter's customer
interface (KS2) needs an add-on module; this integration only reads what myBKW
shows.

This is not an official BKW integration. It uses the API behind the myBKW web
app, which BKW can change at any time.

## Statistics

| Statistic | Unit | Contents |
| --- | --- | --- |
| `bkw:<metering point>_consumption` | kWh | Energy drawn from the grid, per hour |
| `bkw:<metering point>_cost` | your currency | Cost of that energy, once a price is set |

The first run imports everything myBKW has for the metering point. After that the
integration checks every 6 hours and imports any new complete hours.

## Installation

With HACS: add `https://github.com/mbolli/ha-bkw` as a custom repository of type
*Integration*, install **BKW Smart Meter** and restart Home Assistant.

Without HACS: copy `custom_components/bkw` into `/config/custom_components/` and
restart Home Assistant.

## Setup

1. Go to **Settings → Devices & services → Add integration** and choose **BKW
   Smart Meter**.
2. Open the login link in the form and log in to myBKW.
3. The browser lands on a small arrow image on `my.bkw.ch`. Copy the full address
   from the address bar and paste it into the form within a minute.

The login gives the integration an offline token, which BKW keeps valid for 30
days without use. The integration refreshes it on every run. If Home Assistant
is off for more than 30 days, it asks you to log in again.

## Costs

Under **Configure** on the integration, set:

- **Price sensor** or **Fixed price**: the price per kWh, including VAT. Choose
  one, not both.
- **Fixed fees**: the yearly fees that do not depend on consumption, including
  VAT. The integration spreads them evenly over the hours.

On a BKW invoice, the price per kWh is the sum of every line billed in Rp./kWh
(energy, grid use, system services, levies, and the Gemeinde levy if your
municipality charges one), plus VAT. The fixed fees are the lines billed in
CHF/a: Grundtarif for energy and for grid use, and the Messtarif.

Hours are priced when they are imported, normally the day after. Home Assistant
keeps no history of what a price sensor said earlier, so the history imported on
the first run gets the price that applies at that moment. When BKW changes its
tariffs on 1 January, update the options on that day.

## Energy dashboard

Under **Settings → Dashboards → Energy → Grid consumption**, add the
`_consumption` statistic and choose the `_cost` statistic as the statistic that
tracks the total cost.

Devices measured separately, such as a UPS with its own energy sensor, belong
under **Individual devices**. Home Assistant shows them as part of the grid total.
