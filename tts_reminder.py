from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

import pyttsx3
import yaml

TIME_24H_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
REMINDER_LEAD_MINUTES = 3


@dataclass
class Reminder:
	item_time: dt_time
	description: str
	trigger_at: datetime
	event_at: datetime
	processed: bool = False


def parse_item_time(value: str, index: int) -> dt_time:
	if not isinstance(value, str) or not TIME_24H_RE.fullmatch(value):
		raise ValueError(
			f"Item {index}: 'time' must be a 24-hour HH:MM string (example: '08:30')."
		)

	hour, minute = map(int, value.split(":"))
	return dt_time(hour=hour, minute=minute)


def reminder_times_for_today(item_time: dt_time, now: datetime) -> tuple[datetime, datetime]:
	event_dt = datetime.combine(now.date(), item_time)
	trigger_dt = event_dt - timedelta(minutes=REMINDER_LEAD_MINUTES)
	return trigger_dt, event_dt


def load_reminders(items_path: Path) -> list[Reminder]:
	try:
		raw = yaml.safe_load(items_path.read_text(encoding="utf-8"))
	except FileNotFoundError as exc:
		raise FileNotFoundError(f"Missing file: {items_path}") from exc

	if raw is None:
		return []
	if not isinstance(raw, list):
		raise ValueError("items.yml root must be a list of items.")

	reminders: list[Reminder] = []
	now = datetime.now()

	for i, item in enumerate(raw, start=1):
		if not isinstance(item, dict):
			raise ValueError(f"Item {i}: each item must be a mapping/object.")

		item_time = parse_item_time(item.get("time"), i)

		read_flag = item.get("read")
		if not isinstance(read_flag, bool):
			raise ValueError(f"Item {i}: 'read' must be true or false.")

		description = item.get("description")
		if not isinstance(description, str) or not description.strip():
			raise ValueError(f"Item {i}: 'description' must be a non-empty string.")

		if not read_flag:
			description = item.get("time")
		else:
			description = description.strip()

		trigger_at, event_at = reminder_times_for_today(item_time, now)
		reminders.append(
			Reminder(
				item_time=item_time,
				description=description,
				trigger_at=trigger_at,
				event_at=event_at,
			)
		)

	return reminders


def build_tts_engine() -> pyttsx3.Engine:
	engine = pyttsx3.init()
	engine.setProperty("rate", 160)
	voices = engine.getProperty("voices")
	engine.setProperty("voice", voices[1].id)
	engine.setProperty("volume", 0.7)
	return engine


def print_next(reminder: Reminder, now: datetime) -> None:
	delta = reminder.trigger_at - now
	total_seconds = max(0, int(delta.total_seconds()))
	minutes, seconds = divmod(total_seconds, 60)
	print(
		f"Next to read: {reminder.event_at.strftime('%H:%M')} | "
		f"in {minutes:02d}:{seconds:02d} | {reminder.description}",
		flush=True,
	)


def run_scheduler(items_path: Path) -> None:
	reminders = load_reminders(items_path)

	if not reminders:
		print("No readable items found (items with read: true).")
		return

	engine = build_tts_engine()
	print(f"Loaded {len(reminders)} readable item(s) from {items_path}.")

	last_status_key: tuple[str, str] | None = None
	last_status_at: datetime | None = None

	while True:
		now = datetime.now()

		for reminder in reminders:
			if not reminder.processed and now > reminder.event_at:
				reminder.processed = True
				print(f"Skipped (window passed): {reminder.description}", flush=True)

		pending = [r for r in reminders if not r.processed]
		if not pending:
			print("All readable items processed for today.")
			return

		next_reminder = min(pending, key=lambda r: r.trigger_at)

		current_key = (
			next_reminder.trigger_at.isoformat(timespec="minutes"),
			next_reminder.description,
		)

		should_refresh_status = (
			current_key != last_status_key
			or last_status_at is None
			or (now - last_status_at) >= timedelta(seconds=30)
		)

		if should_refresh_status:
			print_next(next_reminder, now)
			last_status_key = current_key
			last_status_at = now

		if next_reminder.trigger_at <= now <= next_reminder.event_at:
			print(f"Reading now: {next_reminder.description}", flush=True)
			engine.say(next_reminder.description)
			engine.runAndWait()

			next_reminder.processed = True
			last_status_key = None

		time.sleep(60)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="YAML-driven TTS reminder CLI")
	parser.add_argument(
		"--items",
		type=Path,
		default=Path("items.yml"),
		help="Path to items YAML file (default: items.yml)",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	try:
		run_scheduler(args.items)
		return 0
	except (ValueError, FileNotFoundError, yaml.YAMLError) as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1
	except KeyboardInterrupt:
		print("\nStopped by user.")
		return 0


if __name__ == "__main__":
	raise SystemExit(main())
