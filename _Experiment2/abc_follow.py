#!/usr/bin/env python

"""
The ego car's answer to an F (abc_config templates F, 2026-11-12): the automation brakes after the
lead car and makes up the distance after it. The other cars keep their speeds, so the ego car falls
behind where the schedule has it (lag); abc_traffic places the cars relative to that place (offset),
the lead car included, until the lag is made up.

Follow.step() each frame, from follow_react_s after the brake: a time-gap ACC on the lead car,
    wanted = lead speed + follow_gain * (gap - (FOLLOW_GAP_M + follow_time_gap_s * own speed))
and at most the nominal speed + min(follow_catch_up_kmh, CATCH_UP_GAIN * lag) (catching up),
changing by at most follow_decel_mps2 / follow_accel_mps2; done once the lead car is back at its place
(the F's span) and the lag under DONE_LAG_M. abc_schedule runs the same law on the planned lead car
(effect_s) to keep the F that long from the questions and the event cars.
"""

FOLLOW_GAP_M = 5.0      # m standstill gap of the time-gap rule
CATCH_UP_GAIN = 0.5     # 1/s: m/s faster per m of lag
DONE_LAG_M = 0.3        # m


class Follow(object):
    def __init__(self, template, t_brake, t_back):
        self.ft = template
        self.t_brake, self.t_back = t_brake, t_back
        self.lag = 0.0          # m behind the schedule's place
        self.most = 0.0         # the largest lag
        self.speed = None       # m/s commanded
        self.done = False

    def active(self, t):
        return not self.done and t >= self.t_brake + self.ft.get('follow_react_s', 1.0)

    def step(self, t, dt, v_nominal, v_ego, gap, v_lead):
        """The ego car's speed (m/s) for this frame, or None (not braking for the F: its own driving).
        v_nominal: what it would drive without the F; gap, v_lead: the lead car (None: not seen)."""
        ft = self.ft
        if self.speed is None:
            self.speed = v_ego
        if self.done or t < self.t_brake + ft.get('follow_react_s', 1.0):
            if not self.done and t >= self.t_brake:
                self.lag += (v_nominal - v_ego) * dt
            self.speed = v_ego
            return None
        want = v_nominal + min(ft.get('follow_catch_up_kmh', 12.0) / 3.6, CATCH_UP_GAIN * max(self.lag, 0.0))
        if gap is not None and v_lead is not None:
            gap_wanted = FOLLOW_GAP_M + ft.get('follow_time_gap_s', 1.4) * max(self.speed, 0.0)
            want = min(want, v_lead + ft.get('follow_gain', 0.3) * (gap - gap_wanted))
        step_down, step_up = ft.get('follow_decel_mps2', 4.0) * dt, ft.get('follow_accel_mps2', 2.0) * dt
        self.speed = max(0.0, self.speed + max(-step_down, min(want - self.speed, step_up)))
        self.lag += (v_nominal - self.speed) * dt
        self.most = max(self.most, self.lag)
        if t > self.t_back and self.lag < DONE_LAG_M:
            self.done = True
        return self.speed


def effect_s(template, xs_of, v_nominal=70 / 3.6, dt=1 / 34.0, t_brake=0.0, t_back=0.0, limit=60.0):
    """The law on a planned lead car (xs_of(t): its dx, m ahead of the schedule's place): (s from the
    brake until the lag is made up, the closest real gap m, the largest lag m, the lowest speed km/h)."""
    follow = Follow(template, t_brake, t_back)
    t, v = t_brake - 1.0, v_nominal
    closest, most, lowest = 1e9, 0.0, v_nominal
    while t < t_brake + limit:
        dx, dx_next = xs_of(t), xs_of(t + 0.1)
        v_lead = v_nominal + (dx_next - dx) / 0.1
        gap = dx + follow.lag
        out = follow.step(t, dt, v_nominal, v, gap, v_lead)
        if out is not None:
            v = out
        else:
            v = v_nominal if not follow.active(t) else v
        closest, most, lowest = min(closest, gap), max(most, follow.lag), min(lowest, v)
        if follow.done:
            return t - t_brake, closest, most, lowest * 3.6
        t += dt
    return limit, closest, most, lowest * 3.6
