get_markets

GetMarketsResponse get_markets(limit=limit, cursor=cursor, event_ticker=event_ticker, series_ticker=series_ticker, max_close_ts=max_close_ts, min_close_ts=min_close_ts, status=status, tickers=tickers)
Get Markets
List and discover markets on Kalshi.
A market represents a specific binary outcome within an event that users can trade on (e.g., “Will candidate X win?”). Markets have yes/no positions, current prices, volume, and settlement rules.
This endpoint returns a paginated response. Use the ‘limit’ parameter to control page size (1-1000, defaults to 100). The response includes a ‘cursor’ field - pass this value in the ‘cursor’ parameter of your next request to get the next page. An empty cursor indicates no more pages are available.
​
Example

----
import kalshi_python
from kalshi_python.models.get_markets_response import GetMarketsResponse
from kalshi_python.rest import ApiException
from pprint import pprint

### Defining the host is optional and defaults to https://api.elections.kalshi.com/trade-api/v2
### See configuration.py for a list of all supported configuration parameters.
configuration = kalshi_python.Configuration(
    host = "https://api.elections.kalshi.com/trade-api/v2"
)

###Read private key from file
with open('path/to/private_key.pem', 'r') as f:
    private_key = f.read()

###Configure API key authentication
configuration.api_key_id = "your-api-key-id"
configuration.private_key_pem = private_key

###Initialize the Kalshi client
client = kalshi_python.KalshiClient(configuration)

limit = 100 # int | Number of results per page. Defaults to 100. Maximum value is 1000. (optional) (default to 100)

cursor = 'cursor_example' # str | Pagination cursor. Use the cursor value returned from the previous response to get the next page of results. Leave empty for the first page. (optional)

event_ticker = 'event_ticker_example' # str | Filter by event ticker (optional)

series_ticker = 'series_ticker_example' # str | Filter by series ticker (optional)

max_close_ts = 56 # int | Filter items that close before this Unix timestamp (optional)

min_close_ts = 56 # int | Filter items that close after this Unix timestamp (optional)

status = 'status_example' # str | Filter by market status. Comma-separated list. Possible values are 'initialized', 'open', 'closed', 'settled', 'determined'. Note that the API accepts 'open' for filtering but returns 'active' in the response. Leave empty to return markets with any status. (optional)

tickers = 'tickers_example' # str | Filter by specific market tickers. Comma-separated list of market tickers to retrieve. (optional)

try:
###Get Markets
    api_response = client.get_markets(limit=limit, cursor=cursor, event_ticker=event_ticker, series_ticker=series_ticker, max_close_ts=max_close_ts, min_close_ts=min_close_ts, status=status, tickers=tickers)
    print("The response of MarketsApi->get_markets:\n")
    pprint(api_response)
except Exception as e:
    print("Exception when calling MarketsApi->get_markets: %s\n" % e)
​
​----
​
Parameters

Name    Type    Description    Notes
limit    int    Number of results per page. Defaults to 100. Maximum value is 1000.    [optional] [default to 100]
cursor    str    Pagination cursor. Use the cursor value returned from the previous response to get the next page of results. Leave empty for the first page.    [optional]
event_ticker    str    Filter by event ticker    [optional]
series_ticker    str    Filter by series ticker    [optional]
max_close_ts    int    Filter items that close before this Unix timestamp    [optional]
min_close_ts    int    Filter items that close after this Unix timestamp    [optional]
status    str    Filter by market status. Comma-separated list. Possible values are ‘initialized’, ‘open’, ‘closed’, ‘settled’, ‘determined’. Note that the API accepts ‘open’ for filtering but returns ‘active’ in the response. Leave empty to return markets with any status.    [optional]
tickers    str    Filter by specific market tickers. Comma-separated list of market tickers to retrieve.    [optional]
