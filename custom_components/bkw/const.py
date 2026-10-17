"""Constants for the BKW Smart Meter integration."""

DOMAIN = "bkw"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_PRICE_ENTITY = "price_entity"
CONF_PRICE = "price"
CONF_FIXED_FEE = "fixed_fee"

AUTH_URL = "https://login.portal-services.ch/auth/realms/oneportal/protocol/openid-connect/auth"
TOKEN_URL = "https://login.portal-services.ch/auth/realms/oneportal/protocol/openid-connect/token"
API_URL = "https://api-energy-monitoring.bkw.ch/api"
CLIENT_ID = "mybkw-webapp"

# A static file on my.bkw.ch: Keycloak accepts it as a redirect target and no
# script runs there, so the authorization code stays in the address bar.
REDIRECT_URI = "https://my.bkw.ch/assets/img/icons/icon-arrow-down.svg"

# The API names flows from BKW's side: PRODUCTION_BKW is what BKW delivers to
# the customer, i.e. the customer's consumption.
DATA_TYPE_CONSUMPTION = "PRODUCTION_BKW"
