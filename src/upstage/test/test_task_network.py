# Copyright (C) 2024 by the Georgia Tech Research Institute (GTRI)

# Licensed under the BSD 3-Clause License.
# See the LICENSE file in the project root for complete license terms and disclaimers.

import pytest
from simpy import Resource as sp_resource
from simpy import Store as sp_store

from upstage.api import (
    Actor,
    Any,
    CartesianLocationChangingState,
    DecisionTask,
    EnvironmentContext,
    Event,
    Get,
    LinearChangingState,
    Put,
    ResourceHold,
    State,
    Task,
    TaskNetworkFactory,
    Wait,
)
from upstage.data_types import CartesianLocation, Location
from upstage.task import process


class CodeFour(Task):
    def task(self, *, actor):
        wait = Event(rehearsal_time_to_complete=float("inf"))
        yield wait


class GroundWait(Task):
    def task(self, *, actor):
        wait = Event(rehearsal_time_to_complete=0.0)
        yield wait


class GroundTakeoffWait(Task):
    def task(self, *, actor):
        destination = self.get_actor_knowledge(actor, "destination")
        if not isinstance(destination, Location):
            destination = destination.location
        arrival_time = self.get_actor_knowledge(actor, "arrival time")
        if arrival_time is None:
            wait_time = 0
        else:
            distance = destination - actor.location
            flight_time = distance / actor.speed
            wait_time = arrival_time - flight_time
        yield Wait(wait_time)


class Takeoff(Task):
    def task(self, *, actor):
        base = actor.base
        runway_request = ResourceHold(base.runway)
        yield runway_request
        takeoff_time = Wait(actor.takeoff_time)
        yield takeoff_time
        yield runway_request
        # HOW WOULD THIS WORK IN TRIAL MODE?
        # what if it's a parking spot token? A token state?
        parking_event = Put(base.parking_tokens, actor.parking_spot)
        yield parking_event
        actor.parking_spot = None
        # set our current location as above the base
        actor.base = None

    def on_interrupt(self, *, actor, cause):
        director = self.get_actor_knowledge(actor, "director")
        if director is not None:
            director.report_failure(actor)


class Fly(Task):
    def task(self, *, actor):
        destination = self.get_actor_knowledge(actor, "destination")
        if not isinstance(destination, Location):
            destination = destination.location
        actor.activate_state(
            state="location",
            task=self,
            speed=actor.speed,
            waypoints=[destination],
        )
        actor.activate_state(
            state="fuel",
            task=self,
            rate=-actor.fuel_burn,
        )

        # assume that locations can do this
        distance = destination - actor.location
        time = distance / actor.speed
        fly_wait = Wait(time)

        yield fly_wait

        actor.deactivate_all_states(task=self)
        intent = self.get_actor_knowledge(actor, "intent")
        next_task = self.get_actor_next_task(actor)

        # if our intent is to land, make sure next task is a landing check
        if intent == "land" and next_task != "LandingCheck":
            self.clear_actor_task_queue(actor)
            self.set_actor_task_queue(
                actor,
                [
                    "LandingCheck",
                ],
            )

    def on_interrupt(self, *, actor, cause):
        # For testing a restart, this flying is fine, since there is only one
        # final destination.
        if cause == "restart":
            actor.speed = 0.5
            return self.INTERRUPT.RESTART
        else:
            return self.INTERRUPT.END


class Loiter(Task):
    def task(self, *, actor):
        # calculate bingo
        time = actor.calculate_bingo()
        loiter_wait = Wait(time)
        actor.activate_state(
            state="fuel",
            task=self,
            fuel_burn_rate=-actor.fuel_burn,
        )
        yield loiter_wait
        actor.deactivate_state(
            state="fuel",
            task=self,
        )
        # TODO: Do we say here what action comes next, or do we let that be a part of the command structure?


class Mission(Task):
    def task(self, *, actor, commander):
        # tell the mission folks you are here
        # they'll give you an event to watch to leave
        leave_event = commander.arrival(actor)
        # set up an alternate bingo leave event
        time = actor.calculate_bingo(max_time=actor.on_mission_time)
        bingo_wait = Wait(time)

        stop_mission = Any(leave_event, bingo_wait)
        actor.activate_state(
            state="fuel",
            task=self,
            fuel_burn_rate=-actor.fuel_burn,
        )
        yield stop_mission
        actor.deactivate_all_states(task=self)


class LandingLocationSelection(DecisionTask):
    def rehearse_decision(self, *, actor):
        base = actor.env.WORLD.bases[0]
        self.set_actor_knowledge(actor, "destination", base)
        self.set_actor_knowledge(actor, "intent", "land")

    def make_decision(self, *, actor):
        # These kinds of cognitive tasks must be zero-time (no yields!)
        landable_bases = [b for b in actor.env.WORLD.bases if b.has_parking(actor)]
        base = landable_bases[0]

        self.set_actor_knowledge(actor, "destination", base)
        self.set_actor_knowledge(actor, "intent", "land")


class LandingLocationPrep(Task):
    def task(self, *, actor):
        base = self.get_actor_knowledge(actor, "destination")
        token_event = Get(base.parking_tokens)
        parking_token = yield token_event
        self.set_actor_knowledge(actor, "parking_token", parking_token)


class LandingCheck(DecisionTask):
    """Task for checking the ability to land at the base an actor is above.

    If landing is available, continue in the task network. Otherwise, reselect a base.
    """

    return_task_list = [
        "LandingLocationSelection",
        "LandingLocationPrep",
        "Fly",
        "LandingCheck",
        "Land",
        "MaintenanceWait",
    ]

    def rehearse_decision(self, *, actor):
        return None

    def make_decision(self, *, actor):
        # get base from the actor's destination
        base = self.get_actor_knowledge(actor, "destination")
        # assert that the base can be landed at
        if not base.operational:
            # clear the queue
            self.clear_actor_task_queue(actor)
            self.clear_actor_knowledge(actor, "destination")
            self.clear_actor_knowledge(actor, "intent")
            # set up for a task network path that gets a new place to land
            self.set_actor_task_queue(actor, self.return_task_list)
        else:
            # check that we are landing
            msg = f"Actor {actor} not landing after check"
            assert self.get_actor_next_task(actor) == "Land", msg


class Land(Task):
    def task(self, *, actor):
        base = self.get_actor_knowledge(actor, "destination")
        self.clear_actor_knowledge(actor, "destination")
        runway_request = ResourceHold(base.runway)

        self.set_marker("pre-runway")
        yield runway_request
        landing_time = Wait(actor.landing_time)

        self.set_marker("during landing")
        yield landing_time

        self.set_marker("post-landing", self.INTERRUPT.IGNORE)
        yield runway_request
        self.clear_marker()

        self.set_actor_knowledge(actor, "base", base)
        # just to help with a 'clear actor from all stores' need?
        put_event = Put(base.parking, actor)
        self.set_marker("get parking", self.INTERRUPT.IGNORE)
        yield put_event

        self.set_marker("post-parking", interrupt_action=self.INTERRUPT.IGNORE)
        parking_token = self.get_actor_knowledge(actor, "parking_token")
        put_event = Put(base.parking_tokens, parking_token)
        yield put_event

        self.clear_actor_knowledge(actor, "parking_token")
        self.clear_actor_knowledge(actor, "intent")

    def on_interrupt(self, *, actor, cause):
        # if interrupted, find a new place to land
        # figure out where we were in the task based on the marker
        marker = self.get_marker()
        self.get_marker_time()
        if marker in [
            "pre-runway",
        ]:
            # We are done with this base
            # put the parking token back
            parking_token = self.get_actor_knowledge(actor, "parking_token")
            if parking_token:
                store = parking_token[1]
                Put(store, parking_token)
                self.clear_actor_knowledge(actor, "parking_token")
            # set the task network to try landing again
            return_task_list = [
                "LandingLocationSelection",
                "LandingLocationPrep",
                "Fly",
                "LandingCheck",
                "Land",
                "MaintenanceWait",
            ]
            self.clear_actor_task_queue(actor)
            self.set_actor_task_queue(actor, return_task_list)
        elif marker in [
            "during landing",
        ]:
            # continue on if the cause is benign
            if cause == "Code 4":
                # clear the knowledge and task queue
                parking_token = self.get_actor_knowledge(actor, "parking_token")
                if parking_token:
                    store = parking_token[1]
                    Put(store, parking_token)
                    self.clear_actor_knowledge(actor, "parking_token")
                self.clear_actor_task_queue(actor)
                self.set_actor_task_queue(actor, ["Code4"])
                return self.INTERRUPT.END
            else:
                return self.INTERRUPT.IGNORE
        else:
            # other markers mean that the landing was safe so no
            # need to do anything
            raise ValueError("Shouldn't be here")


class MaintenanceWait(Task):
    def task(self, *, actor):
        base = self.get_actor_knowledge(actor, "base")
        maintenance_put = Put(base.maintenance_queue, actor)
        yield maintenance_put
        mx_wait = Event(rehearsal_time_to_complete=2.0)
        self.set_actor_knowledge(actor, "mx_wait", mx_wait)
        yield mx_wait
        self.clear_actor_knowledge(actor, "mx_wait")
        # TODO: How to check or set the new MX code in testing

    def on_interrupt(self, *, actor, **kwargs):
        pass


class Aircraft(Actor):
    location = CartesianLocationChangingState(recording=True)
    speed = State()
    landing_time = State()
    takeoff_time = State()
    code = State()
    fuel = LinearChangingState(recording=True)
    fuel_burn = State()
    parking_token = State()
    parking_spot = State()
    command_data = State()
    world = State()

    def calculate_bingo(self, max_time=float("inf")):
        # get the farthest base
        farthest = max(self.world.bases, key=lambda x: self.location - x.location)
        dist = self.location - farthest.location
        time = dist / self.speed
        fuel_needed = self.fuel_burn * time
        time_until_bingo = (self.fuel - fuel_needed) / self.fuel_burn
        return min(time_until_bingo, max_time)


class Base:
    def __init__(
        self,
        env,
        name: str,
        x: float,
        y: float,
        num_runways: int = 1,
        parking_max: int = 10,
    ):
        self.env = env
        self.name = name
        self.location = CartesianLocation(x=x, y=y)
        self.runway = sp_resource(self.env, capacity=num_runways)
        self.maintenance_queue = sp_store(self.env)
        self.parking = sp_store(self.env, parking_max)
        self.parking_tokens = sp_store(self.env, parking_max)
        self.parking_tokens.items = [
            (self, self.parking_tokens, i) for i in range(parking_max)
        ]
        self.operational = True

        # yes, this is weird
        self.location = CartesianLocation(x, y)

        self.parking_max = parking_max
        self.curr_parked = 0
        self.claimed_parking = 0
        self._parking_claims = []
        self._parked = []

    def claim_parking(self, plane):
        self._parking_claims.append(plane)
        self.claimed_parking += 1

    def has_parking(self, plane):
        return self.curr_parked + self.claimed_parking < self.parking_max

    @process
    def run_maintenance(self):
        while True:
            # TODO: THIS IS CLUNKY
            plane = yield Get(self.maintenance_queue).as_event()
            yield Wait(1.6).as_event()
            mx_wait = plane.get_knowledge("mx_wait")
            # alter the plane's code
            plane.code = 0
            mx_wait.succeed()

    def __repr__(self):
        return f"{self.name}:{super().__repr__()}"


class World:
    """A helper class for data storage and environment analysis"""

    def __init__(self, bases):
        self.bases = bases

    def nearest_base(self, loc):
        b = min(self.bases, key=lambda x: x - loc)
        return b

    def bases_by_location(self, loc):
        x, y = (loc.x, loc.y)
        return [b for b in self.bases if b.x == x and b.y == y][0]


BASE_LOCATIONS = [
    (10.023, 4.63),
    (2.409, 7.279),
    (0.529, 11.004),
    (6.468, 17.153),
    (5.802, 17.215),
]

task_classes = {
    "GroundWait": GroundWait,
    "GroundTakeoffWait": GroundTakeoffWait,
    "Takeoff": Takeoff,
    "Fly": Fly,
    "Loiter": Loiter,
    "Mission": Mission,
    "LandingLocationSelection": LandingLocationSelection,
    "LandingLocationPrep": LandingLocationPrep,
    "LandingCheck": LandingCheck,
    "Land": Land,
    "MaintenanceWait": MaintenanceWait,
    "Code4": CodeFour,
}
task_links = {
    "GroundWait": [
        "Takeoff",
        "Code4",
    ],
    "Takeoff": [
        "Fly",
        "Loiter",
        "LandingLocationSelection",
        "Code4",
    ],
    # TODO: Can there be a 'task group' the makes it easier to define 'Land'?
    "Loiter": [
        "Fly",
        "Mission",
        "LandingLocationSelection",
    ],
    "Fly": [
        "Loiter",
        "Mission",
        "LandingLocationSelection",
        "LandingCheck",
        "Fly",
    ],
    "Mission": [
        "Fly",
        "Loiter",
        "LandingLocationSelection",
    ],
    "LandingLocationSelection": [
        "Fly",
        "Loiter",
        "LandingLocationPrep",
    ],
    "LandingLocationPrep": [
        "Fly",
        "Loiter",
        "LandingCheck",
        "LandingLocationSelection",
    ],
    "LandingCheck": [
        "Land",
        "Loiter",
        "Fly",
        "LandingLocationSelection",
    ],
    "Land": [
        "MaintenanceWait",
        "Loiter",
        "Code4",
    ],
    "MaintenanceWait": [
        "GroundWait",
        "Code4",
    ],
    "Code4": [],
}
# quick fix for new task network link style
for k, v in task_links.items():
    new = {"default": v[0] if v else None, "allowed": v}
    task_links[k] = new


def _build_test(env) -> Aircraft:
    bases = []
    for i in range(len(BASE_LOCATIONS)):
        x, y = BASE_LOCATIONS[i]
        b = Base(env, f"Base {i}", x, y)
        bases.append(b)
        b.run_maintenance()

    world = World(bases)
    env.WORLD = world

    p = Aircraft(
        name="my plane",
        location=CartesianLocation(0, 0),
        speed=12,
        landing_time=5 / 60,
        takeoff_time=10 / 60,
        code=2,
        fuel=100,
        fuel_burn=15,
        parking_token=None,
        parking_spot=None,
        command_data=None,
        world=world,
        debug_log=True,
    )

    return p


def test_plane_bingo():
    with EnvironmentContext() as env:
        p = _build_test(env)
        bingo_hours = 5.14
        bingo_result = p.calculate_bingo()
        assert pytest.approx(bingo_result, abs=0.01) == bingo_hours


def test_creating_network():
    with EnvironmentContext():
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        _ = task_fact.make_network()


def test_rehearsing_network():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        actor.add_task_network(net)
        # start the task network
        actor.start_network_loop("plane_net", init_task_name="GroundWait")
        env.run()
        assert env.now == 0

        new_actor = net.rehearse_network(actor=actor, task_name_list=task_name_list)

        # Did the new actor do what we wanted it to?
        base = new_actor.get_knowledge("base")
        base2 = env.WORLD.bases[0]
        # Notice that due to copying the actor, the bases aren't exactly the same
        assert base.name == base2.name, "Wrong base selected"
        assert len(new_actor._knowledge) == 1, "Too much knowledge left"
        assert pytest.approx(new_actor.fuel, abs=0.01) == 86.199

        # Is the original actor untouched?
        assert len(actor._knowledge) == 0, "Actor should not have done anything"

        assert new_actor.code == 2, "Wrong MX code"

        assert new_actor.env.now > 2.0, "Cloned actor environment at the wrong time"

        task_name = actor.get_running_task("plane_net")["name"]
        assert task_name == "GroundWait"


def test_rehearsing_from_actor():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        actor.add_task_network(net)

        new_actor = actor.rehearse_network(
            "plane_net",
            task_name_list,
            knowledge={"dummy_know": 8675309},
        )

        # Make sure the knowledge was set on the copy, but not the original
        assert actor.get_knowledge("dummy_know") is None
        assert new_actor.get_knowledge("dummy_know") == 8675309

        # Did the new actor do what we wanted it to?
        base = new_actor.get_knowledge("base")
        base2 = env.WORLD.bases[0]
        # Notice that due to copying the actor, the bases aren't exactly the same
        assert base.name == base2.name, "Wrong base selected"
        assert len(new_actor._knowledge) == 2, "Too much knowledge left"
        assert pytest.approx(new_actor.fuel, abs=0.01) == 86.199

        # Is the original actor untouched?
        assert len(actor._knowledge) == 0, "Actor should not have done anything"
        assert new_actor.code == 2, "Wrong MX code"

        assert new_actor.env.now > 2.0, "Cloned actor environment at the wrong time"


def test_running_simple_network():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        assert str(net) == "Task network: plane_net"

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        # tell the actor the queue its getting
        actor.add_task_network(net)
        actor.set_task_queue("plane_net", task_name_list)

        # run the queue with the network
        net.loop(actor=actor)
        env.run()

        base = actor.get_knowledge("base")
        base2 = env.WORLD.bases[0]
        assert base is base2, "Wrong base selected"
        assert len(actor._knowledge) == 1, "Too much knowledge left"
        assert pytest.approx(actor.fuel, abs=0.01) == 86.199
        assert actor.code == 0, "Wrong MX code"


def test_interrupting_network():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        # tell the actor the queue its getting
        actor.add_task_network(net)
        actor.set_task_queue("plane_net", task_name_list)

        # create a process that interrupts the plane during different times
        def interrupting_proc(env, actor, interrupt_time):
            yield env.timeout(interrupt_time)
            # get the process
            network = actor._task_networks["plane_net"]
            network._current_task_proc.interrupt(cause="a reason")

        # run the queue with the network
        net.loop(actor=actor)
        env.process(interrupting_proc(env, actor, 1.0))
        env.run()

        # the plane should land still
        assert actor._task_queue["plane_net"] == [], "Actor had tasks left"
        assert actor.code == 0, "Actor didn't get maintained"


def test_interrupting_network_with_cause():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        # tell the actor the queue its getting
        actor.add_task_network(net)
        actor.set_task_queue("plane_net", task_name_list)

        # create a process that interrupts the plane during different times
        def interrupting_proc(env, actor, interrupt_time):
            yield env.timeout(interrupt_time)
            # get the process
            # network = actor._task_networks["plane_net"]
            # network._current_task_proc.interrupt(cause="Code 4")
            actor.interrupt_network("plane_net", cause="Code 4")

        # run the queue with the network
        net.loop(actor=actor)
        env.process(interrupting_proc(env, actor, 1.0))
        env.run()


def test_interrupting_network_with_restart():
    with EnvironmentContext() as env:
        actor = _build_test(env)
        task_fact = TaskNetworkFactory(
            "plane_net",
            task_classes,
            task_links,
        )
        net = task_fact.make_network()

        # build arguments for the task list
        task_name_list = [
            "LandingLocationSelection",
            "LandingLocationPrep",
            "Fly",
            "LandingCheck",
            "Land",
            "MaintenanceWait",
        ]

        # tell the actor the queue its getting
        actor.add_task_network(net)
        actor.set_task_queue("plane_net", task_name_list)

        # create a process that interrupts the plane during different times
        def interrupting_proc(env, actor, interrupt_time):
            yield env.timeout(interrupt_time)
            # get the process
            network = actor._task_networks["plane_net"]
            assert network._current_task_name == "Fly"
            network._current_task_proc.interrupt(cause="restart")

        # run the queue with the network
        net.loop(actor=actor)
        env.process(interrupting_proc(env, actor, 0.1))
        env.run()
        # the plane should land still
        assert actor._task_queue["plane_net"] == [], "Actor had tasks left"
        assert actor.code == 0, "Actor didn't get maintained"
        # it should take longer than the cancelled version
        assert pytest.approx(env.now, abs=0.0001) == 21.464767


def test_rehearsal_time():
    class Thing(Actor):
        the_time = LinearChangingState(recording=True)

    class ThingWait(Task):
        def task(self, *, actor):
            actor.activate_state(
                state="the_time",
                task=self,
                rate=1.0,
            )
            yield Wait.from_random_uniform(1.0, 2.0)
            actor.deactivate_all_states(task=self)

    with EnvironmentContext():
        tasks = {"ThingWait": ThingWait}
        task_links = {"ThingWait": {"default": "ThingWait", "allowed": ["ThingWait"]}}
        factory = TaskNetworkFactory("fact", tasks, task_links)

        thing = Thing(name="Actor", the_time=0)
        thing.add_task_network(factory.make_network())
        new_thing = thing.rehearse_network("fact", ["ThingWait", "ThingWait"])
        assert new_thing.env.now == new_thing.the_time, "Bad rehearsal env time"