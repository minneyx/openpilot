#!/usr/bin/env python3
# type: ignore

import os
import argparse
import signal
from collections import defaultdict

import cereal.messaging as messaging

def sigint_handler(signal, frame):
  print("handler!")
  exit(0)
signal.signal(signal.SIGINT, sigint_handler)

if __name__ == "__main__":

  parser = argparse.ArgumentParser(description='Sniff a communication socket')
  parser.add_argument('control_type', help="[pid|indi|lqr|angle]")
  parser.add_argument('--addr', default='127.0.0.1', help="IP address for optional ZMQ listener, default to msgq")
  parser.add_argument('--group', default='all', help="speed group to display, [crawl|slow|medium|fast|veryfast|germany|all], default to all")
  args = parser.parse_args()

  if args.addr != "127.0.0.1":
    os.environ["ZMQ"] = "1"
    messaging.context = messaging.Context()

  all_groups = {"germany":  (45, "45 - up m/s  |  101 -  up mph  |  162 -  up km/h"),
                "veryfast": (35, "35 - 45 m/s  |   78 - 101 mph  |  126 - 162 km/h"),
                "fast":     (25, "25 - 35 m/s  |   56 -  78 mph  |   90 - 126 km/h"),
                "medium":   (15, "15 - 25 m/s  |   34 -  56 mph  |   54 -  90 km/h"),
                "slow":     (5,  " 5 - 15 m/s  |   11 -  34 mph  |   18 -  54 km/h"),
                "crawl":    (0,  " 0 -  5 m/s  |    0 -  11 mph  |    0 -  18 km/h")}

  if args.group == "all":
    display_groups = all_groups.keys()
  elif args.group in all_groups.keys():
    display_groups = [args.group]
  else:
    raise ValueError("invalid speed group, see help")

  speed_group_stats = {}
  for group in all_groups:
    speed_group_stats[group] = defaultdict(lambda: {'err': 0, "cnt": 0, "saturated": 0, "=": 0, "+": 0, "-": 0})

  carControl = messaging.sub_sock('carControl', addr=args.addr, conflate=True)
  sm = messaging.SubMaster(['carState', 'carControl', 'controlsState'], addr=args.addr)

  msg_cnt = 0
  cnt = 0
  total_error = 0

  while messaging.recv_one(carControl):
    sm.update()
    msg_cnt += 1

    actual_speed = sm['carState'].vEgo
    active = sm['controlsState'].active
    steer_override = sm['carState'].steeringPressed
    if args.control_type == "pid":
      control_state = sm['controlsState'].lateralControlState.pidState
    elif args.control_type == "indi":
      control_state = sm['controlsState'].lateralControlState.indiState
    elif args.control_type == "lqr":
      control_state = sm['controlsState'].lateralControlState.lqrState
    elif args.control_type == "angle":
      control_state = sm['controlsState'].lateralControlState.angleState
    else:
      raise ValueError("invalid lateral control type, see help")

    # must be engaged, not at standstill, and not overriding steering
    if sm['controlsState'].active and not sm['carState'].standstill and not sm['carState'].steeringPressed:
      cnt += 1

      # wait 5 seconds after engage/override/standstill
      if cnt >= 500:
        actual_angle = control_state.steeringAngleDeg
        desired_angle = control_state.steeringAngleDesiredDeg

        # calculate error before rounding, then round for stats grouping
        angle_error = abs(desired_angle - actual_angle)
        actual_angle = round(actual_angle, 1)
        desired_angle = round(desired_angle, 1)
        angle_error = round(angle_error, 2)
        angle_abs = int(abs(round(desired_angle, 0)))

        for group, group_props in all_groups.items():
          if actual_speed > group_props[0]:
            # collect stats
            speed_group_stats[group][angle_abs]["err"] += angle_error
            speed_group_stats[group][angle_abs]["cnt"] += 1
            if control_state.saturated:
              speed_group_stats[group][angle_abs]["saturated"] += 1
            if actual_angle == desired_angle:
              speed_group_stats[group][angle_abs]["="] += 1
            else:
              if desired_angle == 0.:
                overshoot = True
              else:
                overshoot = desired_angle < actual_angle if desired_angle > 0. else desired_angle > actual_angle
              speed_group_stats[group][angle_abs]["+" if overshoot else "-"] += 1
            break
    else:
      cnt = 0

    if msg_cnt % 100 == 0:
      print(chr(27) + "[2J")
      if cnt != 0:
        print("COLLECTING ...\n")
      else:
        print("DISABLED (standstill, not active, or steer override)\n")
      for group in display_groups:
        if len(speed_group_stats[group]) > 0:
          print(f"speed group: {group:18s} {all_groups[group][1]}")
          print(f"  {'-'*78}")
          for k in sorted(speed_group_stats[group].keys()):
            v = speed_group_stats[group][k]
            print(f'  angle: {k:#2} | error: {round(v["err"] / v["cnt"], 2):2.2f} | =:{int(v["="] / v["cnt"] * 100):#3}% | +:{int(v["+"] / v["cnt"] * 100):#4}% | -:{int(v["-"] / v["cnt"] * 100):#3}% | sat: {v["saturated"]:#4} | count: {v["cnt"]:#5}')
          print("")
