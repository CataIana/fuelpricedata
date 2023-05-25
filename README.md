# Daily fuel price data

This app fetches fuel data daily from the NSW Government and parses it into a readable graph sent to your service of choice.

API documentation that is utilised is available [here](https://api.nsw.gov.au/Product/Index/22#v-pills-doc).

This app utilises the Get All Prices (v2) method

This app relies on past data to generate graphs, so initial graphs will lack data until at least a month's history has been fetched




## Setup
I didn't make this to share but these basic setup should get you far enough to get it working.

1. Create an account and subscribe to the Fuel API [here](https://api.nsw.gov.au/Product/Index/22)
2. Rename exampleconfig.json to config.json and fill in the necessary variables
3. Modify the script to output to your service of choice and customise the desired notification time. Currently the script outputs to a https://ntfy.sh server, or a discord webhook
4. Install dependencies from requirements.txt
5. Run the script, ideally as a service
