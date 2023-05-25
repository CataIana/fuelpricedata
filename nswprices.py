import json
import logging
import os
import sys
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from time import sleep
from io import BytesIO
import matplotlib.pyplot as plt
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil import tz
from requests import Session
from disnake import SyncWebhook, File, Embed

class NSWFuelPriceTrends:
    base = "https://api.onegov.nsw.gov.au"
    tzname = "Australia/Sydney"
    hour_trigger = 8
    minute_trigger = 58
    graph_history_days = 30

    def __init__(self):
        self.init_scheduler()

        # Init log
        self.log: logging.Logger = logging.getLogger("Fuel Price Trends")
        self.log.setLevel(logging.INFO)

        shandler = logging.StreamHandler(sys.stdout)
        shandler.setLevel(self.log.level)
        shandler.setFormatter(logging.Formatter(
            '%(funcName)-12s || %(levelname)-8s || %(message)s'))
        self.log.addHandler(shandler)

        # Init Config
        config = self.get_config()
        self.api_key: str = config["api_key"]
        self.api_secret: str = config["api_secret"]
        self.fuel_types: str = config["fuel_types"]
        self.enable_ntfy: bool = config["enable_ntfy"]
        self.ntfy_uri: str = config.get("ntfy_uri")
        self.ntfy_domain: str = config.get("ntfy_attachment_uri_domain")
        self.ntfy_token: str = config.get("ntfy_token")
        self.enable_discord: bool = config["enable_discord"]
        self.discord_webhook: str = config["discord_webhook"]

        with open("codes.json") as f:
            self.codes: dict = json.load(f)

        self.tz = tz.gettz(self.tzname)

        self.session = Session()

    def init_scheduler(self):
        scheduler = BackgroundScheduler()
        scheduler.start()

        trigger = CronTrigger(
            year="*", month="*", day="*", 
            hour=self.hour_trigger, minute=self.minute_trigger, second="0", 
            timezone=self.tzname
        )
        scheduler.add_job(
            self.update_data, trigger=trigger,
            name="Daily Fuel Check"
        )

    def main(self):
        # Check if today's data has been requested, otherwise just loop
        self.fetch_access_token()
        self.fetch_todays_prices()
        # self.generate_graph() 
        while True:
            sleep(5)

    def to_b64(self, data: str) -> str:
        return b64encode(data.encode("utf-8")).decode()

    def utcnow(self) -> datetime:
        """Returns a timezone aware UTC Datetime Object"""
        return datetime.now(timezone.utc)

    def get_config(self) -> dict:
        with open("config.json") as f:
            return json.load(f)

    def write_config(self, config: dict):
        with open("config.json", "w") as f:
            f.write(json.dumps(config, indent=4))    

    def get_transaction_id(self) -> str:
        """Get unique transaction ID and iterate by one"""
        config = self.get_config()
        id = config.get("transaction_id", 0)
        config["transaction_id"] = id + 1
        self.write_config(config)
        return str(id)

    def access_token_expired(self, config: dict) -> bool:
        return config.get("expires_at", 0) < datetime.utcnow().timestamp() or not config.get("access_token", None)

    def fetch_access_token(self) -> None:
        """Fetches new access token if needed or assigns a cached token to self.access_token"""
        config = self.get_config()
        if self.access_token_expired(config):
            header = {
                "Authorization": f"Basic {self.to_b64(f'{self.api_key}:{self.api_secret}')}"
            }
            response = self.session.get(
                f"{self.base}/oauth/client_credential/accesstoken?grant_type=client_credentials", headers=header)
            rj = response.json()
            self.access_token = rj["access_token"]
            config["access_token"] = rj["access_token"]
            # Write expires in date, removing 10 minutes just in case
            config["expires_at"] = int(datetime.utcnow().timestamp()) + int(rj["expires_in"]) - 600
            self.write_config(config)
        else:
            self.access_token = config["access_token"]

    def fetch_todays_prices(self, now: datetime = None) -> dict:
        now = now or self.utcnow()
        # Check if today has already been requested
        file_date = now.astimezone(self.tz).strftime("prices/%Y/%m/%d.json")
        try:
            with open(file_date) as f:
                return json.load(f)
        except (FileNotFoundError, json.decoder.JSONDecodeError):
            self.log.warning("Today's prices not found, fetching new")

        # Make request for new prices
        header = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=utf-8", "apikey": self.api_key,
            "transactionid": self.get_transaction_id(), 
            "requesttimestamp": now.strftime("%d/%m/%Y %I:%M:%S %p")
        }
        response = self.session.get(
            f"{self.base}/FuelPriceCheck/v2/fuel/prices?states=NSW", headers=header)
        if response.status_code != 200:
            self.log.error(f"{response.status_code}: {response.json()}")
            return
        rj: dict = response.json()
        # Add request timestamp to file for later use
        rj["request_time"] = int(now.timestamp())

        # Create history folder
        if not os.path.isdir("prices"):
            os.mkdir("prices")
        if not os.path.isdir(f"prices/{now.year}"):
            os.mkdir(f"prices/{now.year}")
        if not os.path.isdir(f"prices/{now.year}/{now.month:02d}"):
            os.mkdir(f"prices/{now.year}/{now.month:02d}")

        # Remove uncessary data to save space
        rj.pop("stations", None)
        
        # Write newly fetched data
        with open(file_date, "w") as f:
            f.write(json.dumps(rj, indent=4))
        return rj

    def update_data(self):
        # Check if expired and then fetch new token if so
        self.fetch_access_token()

        now = self.utcnow()

        prices = self.fetch_todays_prices(now)

        total_prices: dict[str, list] = {}

        for station in prices["prices"]:
            if total_prices.get(station["fueltype"], None) == None:
                total_prices[station["fueltype"]] = []
            total_prices[station["fueltype"]].append(station["price"])

        for fuel_type, total in total_prices.items():
            print(
                f"{self.codes[fuel_type]}: {round(sum(total)/len(total), 2)} || Stations: {len(total)}")

        self.generate_graph(now)

    def generate_graph(self, now: datetime = None):
        now = now or self.utcnow()
        fig, ax = plt.subplots()
        now_tz = now.astimezone(self.tz)

        # How many days to go back

        #                       day  raw data
        price_history_raw: dict[str, dict[str, dict]] = {}
        # Create a dictionary that contains each day of raw data fuel prices with the key being day/month.
        for i in range(0, self.graph_history_days):
            delta = now_tz-timedelta(days=i)
            try:
                with open(f"prices/{delta.strftime('%Y/%m/%d.json')}") as f:
                    price_history_raw[delta.strftime("%d/%m")] = json.load(f)
            except FileNotFoundError:
                self.log.warning(f"Failed to get data for day {delta.strftime('%d/%m')}")
                continue

        # Create a dictionary that contains the averages of each day of fuel data for each fuel type
        # Data is from newest to oldest
        price_history: dict[str, list[int]] = {k: [] for k in self.fuel_types}

        for day in price_history_raw.values():

            prices_for_day: dict[str, list[int]] = {}

            for station in day["prices"]:
                # Ignore fuel types not in list
                if station["fueltype"] not in self.fuel_types:
                    continue

                # Create an array of all prices for that day
                if prices_for_day.get(station["fueltype"], None) == None:
                    prices_for_day[station["fueltype"]] = []
                prices_for_day[station["fueltype"]].append(station["price"])

            # Create averages for each day of fuel data
            for type, prices in prices_for_day.items():
                if price_history.get(type, None) == None:
                    price_history[type] = []
                price_history[type].append(round(sum(prices)/len(prices), 2))

        # Reverse data with [::-1] so that is it from oldest to newest
        for prices in price_history.values():
            spaced_dates = []
            for i, d in enumerate(list(price_history_raw.keys())):
                if i % (self.graph_history_days/10) != 0 and i != 0:
                    spaced_dates.append(i*" ")
                else:
                    spaced_dates.append(d)
            ax.plot(spaced_dates[::-1], prices[::-1], marker="o")

        # self.log.info("Daily Averages - Newest to Oldest")
        # for fuel_type, daily_averages in price_history.items():
        #     self.log.info(f"{fuel_type}: {daily_averages}")

        # Make a percentage based change on data from the previous day
        changes = {}
        for fuel_type, p_avg in price_history.items():
            diff = round((p_avg[0]-p_avg[1])/((p_avg[0]+p_avg[1])/2)*100, 2)
            if diff != 0.0:
                changes[fuel_type] = diff
        
        changes_up_or_down = "chart_with_upwards_trend" if sum(changes.values())/len(changes.values()) > 0 else "chart_with_downwards_trend"

        changes_readable = ""
        self.log.info("Today's fuel averages:")
        for f_type, diff in changes.items():
            s = f"{f_type}: {price_history[f_type][0]} ({'+' if diff > 0 else ''}{diff}%)"
            self.log.info(s)
            changes_readable += f"{s}\n"

        fig.legend(list(price_history.keys()), loc="upper right")

        ax.set_title(f"Fuel Price Averages over the last {self.graph_history_days} days")
        ax.set_xlabel("Date")
        ax.set_ylabel("c/Litre")

        # Create archive folders
        if not os.path.isdir("archive"):
            os.mkdir("archive")
        if not os.path.isdir(f"archive/{now_tz.year}"):
            os.mkdir(f"archive/{now_tz.year}")
        if not os.path.isdir(f"archive/{now_tz.year}/{now_tz.month:02d}"):
            os.mkdir(f"archive/{now_tz.year}/{now_tz.month:02d}")

        plt.grid(True)
        location = now_tz.strftime("%Y/%m/%d")
        plt.savefig(f"archive/{location}.png", format='png')
        if self.enable_ntfy:
            r = self.session.put(self.ntfy_uri,
                        data=f"Today's fuel averages\n{changes_readable}",
                        headers={
                            "Title": f"Fuel Diff for {now_tz.strftime('%d/%m/%Y')}",
                            "Attach": f"{self.ntfy_domain}/{location}",
                            "Tags": changes_up_or_down,
                            "Authorization": f"Bearer {self.ntfy_token}"
                        }
                    )
            r.raise_for_status()
        elif self.enable_discord:
            bytes = BytesIO()
            plt.savefig(bytes, format='png')
            bytes.seek(0)
            hook = SyncWebhook.from_url(self.discord_webhook)
            embed = Embed(title=f"Today's fuel averages ({now.strftime('%Y/%m/%d')}", description=changes_readable)
            embed.set_image(url="attachment://graph.png")
            hook.send(embed=embed, file=File(fp=bytes, filename="graph.png"))
        plt.clf()
        plt.close()



if __name__ == "__main__":
    p = NSWFuelPriceTrends()
    p.main()
