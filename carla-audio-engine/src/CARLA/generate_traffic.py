#!/usr/bin/env python

# Copyright (c) 2021 Computer Vision Center (CVC) at the Universitat Autonoma de
# Barcelona (UAB).
#
# This work is licensed under the terms of the MIT license.
# For a copy, see <https://opensource.org/licenses/MIT>.
"""Traffic generation script for asynchronous CARLA simulation.

This module is based on the official CARLA examples and has been specifically 
adapted to support asynchronous mode for the SoundCARLA project. It handles 
spawning actors, managing traffic, and ensuring synchronization between the 
simulator and the audio engine.

Note:
    This script requires a running CARLA server and should be used with 
    caution regarding performance when spawning a high number of NPCs.

See Also:
    For a detailed technical reference of the classes used here, 
    consult the :carla_docs:`Python API <python_api>`.
"""

import glob
import os
import sys
import time
import argparse
import logging
from numpy import random

try:
    sys.path.append(glob.glob('../carla/dist/carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import carla

def get_actor_blueprints(world, filter, generation):
    bps = world.get_blueprint_library().filter(filter)
    if generation.lower() == "all":
        return bps
    if len(bps) == 1:
        return bps
    try:
        int_generation = int(generation)
        if int_generation in [1, 2, 3]:
            bps = [x for x in bps if int(x.get_attribute('generation')) == int_generation]
            return bps
        else:
            print("   Warning! Actor Generation is not valid. No actor will be spawned.")
            return []
    except:
        print("   Warning! Actor Generation is not valid. No actor will be spawned.")
        return []

def main():
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--host', metavar='H', default='127.0.0.1', help='IP of the host server')
    argparser.add_argument('-p', '--port', metavar='P', default=2000, type=int, help='TCP port')
    argparser.add_argument('-n', '--number-of-vehicles', metavar='N', default=30, type=int, help='Number of vehicles')
    argparser.add_argument('-w', '--number-of-walkers', metavar='W', default=10, type=int, help='Number of walkers')
    argparser.add_argument('--safe', action='store_true', help='Avoid accident-prone vehicles')
    argparser.add_argument('--filterv', metavar='PATTERN', default='vehicle.*', help='Filter vehicle model')
    argparser.add_argument('--generationv', metavar='G', default='All', help='Vehicle generation')
    argparser.add_argument('--filterw', metavar='PATTERN', default='walker.pedestrian.*', help='Filter pedestrian type')
    argparser.add_argument('--generationw', metavar='G', default='2', help='Pedestrian generation')
    argparser.add_argument('--tm-port', metavar='P', default=8000, type=int, help='Port for TM')
    argparser.add_argument('--hybrid', action='store_true', help='Activate hybrid mode for TM')
    argparser.add_argument('-s', '--seed', metavar='S', type=int, help='Random seed')
    argparser.add_argument('--seedw', metavar='S', default=0, type=int, help='Seed for pedestrians')
    argparser.add_argument('--car-lights-on', action='store_true', default=False, help='Enable car lights')
    argparser.add_argument('--respawn', action='store_true', default=False, help='Automatically respawn vehicles')

    args = argparser.parse_args()
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

    vehicles_list = []
    walkers_list = []
    all_id = []
    
    client = carla.Client(args.host, args.port)
    client.set_timeout(20.0)
    random.seed(args.seed if args.seed is not None else int(time.time()))

    try:
        world = client.get_world()
        traffic_manager = client.get_trafficmanager(args.tm_port)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        
        # WICHTIG: Traffic Manager auf ASYNCHRON stellen
        traffic_manager.set_synchronous_mode(False)

        if args.respawn:
            traffic_manager.set_respawn_dormant_vehicles(True)
        if args.hybrid:
            traffic_manager.set_hybrid_physics_mode(True)
            traffic_manager.set_hybrid_physics_radius(70.0)

        # Wir ändern hier KEINE world.settings, damit deine Main die Kontrolle behält.

        blueprints = get_actor_blueprints(world, args.filterv, args.generationv)
        blueprintsWalkers = get_actor_blueprints(world, args.filterw, args.generationw)

        if args.safe:
            blueprints = [x for x in blueprints if x.get_attribute('base_type') == 'car']

        blueprints = sorted(blueprints, key=lambda bp: bp.id)
        spawn_points = world.get_map().get_spawn_points()
        number_of_spawn_points = len(spawn_points)

        if args.number_of_vehicles < number_of_spawn_points:
            random.shuffle(spawn_points)
        else:
            args.number_of_vehicles = number_of_spawn_points

        SpawnActor = carla.command.SpawnActor
        SetAutopilot = carla.command.SetAutopilot
        FutureActor = carla.command.FutureActor

        # Fahrzeuge spawnen
        batch = []
        for n, transform in enumerate(spawn_points):
            if n >= args.number_of_vehicles:
                break
            blueprint = random.choice(blueprints)
            if blueprint.has_attribute('color'):
                color = random.choice(blueprint.get_attribute('color').recommended_values)
                blueprint.set_attribute('color', color)
            blueprint.set_attribute('role_name', 'autopilot')

            batch.append(SpawnActor(blueprint, transform)
                .then(SetAutopilot(FutureActor, True, traffic_manager.get_port())))

        for response in client.apply_batch_sync(batch, False):
            if not response.error:
                vehicles_list.append(response.actor_id)

        # Walker spawnen
        spawn_points_walkers = []
        for i in range(args.number_of_walkers):
            loc = world.get_random_location_from_navigation()
            if loc is not None:
                spawn_point = carla.Transform()
                spawn_point.location = loc
                spawn_points_walkers.append(spawn_point)

        batch = []
        walker_speed = []
        for spawn_point in spawn_points_walkers:
            walker_bp = random.choice(blueprintsWalkers)
            if walker_bp.has_attribute('is_invincible'):
                walker_bp.set_attribute('is_invincible', 'false')
            if walker_bp.has_attribute('speed'):
                walker_speed.append(walker_bp.get_attribute('speed').recommended_values[1])
            else:
                walker_speed.append(0.0)
            batch.append(SpawnActor(walker_bp, spawn_point))

        results = client.apply_batch_sync(batch, False)
        for i in range(len(results)):
            if not results[i].error:
                walkers_list.append({"id": results[i].actor_id})

        # Walker Controller
        batch = []
        walker_controller_bp = world.get_blueprint_library().find('controller.ai.walker')
        for i in range(len(walkers_list)):
            batch.append(SpawnActor(walker_controller_bp, carla.Transform(), walkers_list[i]["id"]))
        
        results = client.apply_batch_sync(batch, False)
        for i in range(len(results)):
            if not results[i].error:
                walkers_list[i]["con"] = results[i].actor_id

        for i in range(len(walkers_list)):
            all_id.append(walkers_list[i]["con"])
            all_id.append(walkers_list[i]["id"])
        
        all_actors = world.get_actors(all_id)
        for i in range(0, len(all_id), 2):
            all_actors[i].start()
            all_actors[i].go_to_location(world.get_random_location_from_navigation())
            all_actors[i].set_max_speed(float(walker_speed[int(i/2)]))

        print('Traffic spawned. Running in ASYNC mode.')

        while True:
            # Wir warten einfach nur auf den nächsten Frame vom Server
            world.wait_for_tick()

    finally:
        print('\ndestroying actors')
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicles_list])
        for i in range(0, len(all_id), 2):
            all_actors[i].stop()
        client.apply_batch([carla.command.DestroyActor(x) for x in all_id])
        time.sleep(0.5)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        print('\ndone.')