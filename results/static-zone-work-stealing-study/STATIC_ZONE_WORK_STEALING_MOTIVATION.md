# Static-Zone Hotspot and Work-Stealing Motivation

## Purpose

This focused 8-zone study establishes the motivation in two steps: first, it shows how a single-zone hotspot strands resources under strict fixed ownership; second, it measures the movement cost of assigning one cold-zone helper to the hot zone.

## Observation 1: a hotspot creates fixed-owner imbalance

The balanced workload assigns 12.5% of active glass tasks to Zone 0 and completes in 0.74 h with 96.8% useful zone-time capacity.
When Zone 0 owns 80.0% of the same-size task batch, completion grows to 4.59 h (6.21x) and 84.4% of zone-time capacity is idle while the panel drains.

> The panel does not lack aggregate resources; strict ownership prevents non-owning resources from serving the hot queue.

## Observation 2: one helper restores parallelism at a movement cost

The nearest evaluated helper is Zone 2 (6.0s center-to-center travel). It steals 208.8 tasks on average, reduces makespan by 40.6%, and adds 0.68 h of aggregate shuttle travel.
The farthest evaluated helper is Zone 7 (27.0s center-to-center travel). It reduces makespan by 27.4% while adding 1.91 h of aggregate shuttle travel.

The helper results should be interpreted as a collision-free movement baseline. They show the direct travel burden of remote assistance, but do not yet include waiting imposed on intermediate zones or congestion caused by multiple helpers entering the hotspot.

## Motivation transition

Static zones provide predictable local traffic, but a hotspot ties completion to one owner. Work stealing can use idle capacity, yet the helper must repeatedly carry hot-zone platters across fixed service regions. This creates the next research question: how should the controller select and bound helpers so that completion-time gains justify the added cross-zone movement and interference risk?

## Figure guide

- `fig1_static_hotspot_motivation`: hotspot strength versus makespan and useful capacity.
- `fig2_static_zone_timeline`: per-zone work and idle intervals for balanced and strong-hotspot workloads.
- `fig3_helper_distance`: one-helper completion benefit and added travel by helper location.
- `fig4_work_stealing_tradeoff`: completion-time gain versus added shuttle travel.

## Evidence boundaries

- Workloads are controlled synthetic batches of unique glass tasks.
- A helper finishes its own queue, uses its local reader for stolen platters, and returns each platter to its original slot.
- Hot tasks are assigned greedily between the local owner and one fixed helper.
- Cross-zone travel time is modeled using the panel movement parameters.
- Route conflicts, collision waiting, intermediate-zone interference, and multi-helper ingress congestion are not modeled.
