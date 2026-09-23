# Buffered Glass-Library Architecture Notes

## Overview

The active architecture pilot is a fixed 32-rack, 16 m glass library with 32 rack-side shuttles, 8 readers, and feeder-buffer handoff. The goal is to preserve rack locality while overlapping platter retrieval with reader service.

## Components

- Rack-local shuttle: fetches a requested platter to its rack-facing input port and returns completed platters home.
- Input feeder buffer: holds up to four demand-driven platters for one reader group.
- Reader-side loader: fixed station mechanism that transfers staged platters into and out of one reader.
- Reader: performs serialized load, mount, optical read, and unload service.
- Output staging: holds completed platters until rack shuttles return them.

## Request Flow

Requests preserve Azure trace arrival order. Requests already queued for one available platter merge at dispatch. The platter moves from its home slot to a rack-facing port, waits in the input buffer, enters the reader, moves to output staging, and finally returns home.

## Data Model

The simulator tracks Request, Platter, Rack, Shuttle, Reader, BufferSlot, and Service records. A platter has one physical home rack and cannot start another fetch until its prior return completes.

## Scalability Boundary

This experiment fixes 32 racks, 32 rack-side shuttles, and 8 readers. It does not claim a scale-out trend. Reader utilization indicates whether the fixed transport layer keeps the expensive readers supplied.

## Bottlenecks

- Cross-rack dispatch can destroy locality and increase crab movement.
- Shared No-Zone trajectories can accumulate prioritized conflict waiting.
- A full input buffer stalls the delivering rack shuttle outside the modeled buffer.
- Output backlog can delay platter reuse; the pilot prioritizes returns at 32 waiting platters.
- Reader-side loader geometry is abstracted into reader load/unload time.

## Assumptions

- Rack centerlines are 1 m apart and shuttle clearance is 0.65 m.
- Zone movement remains on dedicated rack paths and is conflict-free by construction.
- No-Zone uses direct shortest routes with waiting, not global MAPF.
- Reader-side loaders are fixed station resources and are not included in the 32 rack-shuttle count.
- Physical Azure glass addresses are unavailable; placement is seeded and paired across policies.

See [the pilot note](buffered-32rack-pilot.md) and [the rendered architecture diagram](../diagrams/buffered-32rack-architecture.svg).
