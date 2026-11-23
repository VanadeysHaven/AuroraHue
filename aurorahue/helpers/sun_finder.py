from datetime import UTC, datetime, timedelta

from astral import Observer
from astral.sun import sun

from aurorahue.config import Config


def get_times(lat, long, now):
    observer = Observer(latitude=lat, longitude=long)
    times = sun(observer, date=now.date())
    return times["sunrise"], times["sunset"]


def is_daytime(config: Config, now=None) -> bool:
    if now is None:
        now = datetime.now(UTC)

    sunrise, sunset = get_times(lat=config.latitude, long=config.longitude, now=now)

    return sunrise + timedelta(minutes=30) < now < sunset - timedelta(minutes=30)


def get_sun_phase_message(config: Config, now=None):
    if now is None:
        now = datetime.now(UTC)

    sunrise, sunset = get_times(lat=config.latitude, long=config.longitude, now=now)

    since_sunrise = now - sunrise
    until_sunset = sunset - now

    if since_sunrise <= until_sunset:
        minutes = round(since_sunrise.total_seconds() / 60)
        return f"Sunrise was {minutes} minutes ago."

    minutes = round(until_sunset.total_seconds() / 60)
    return f"Sunset is in {minutes} minutes."
