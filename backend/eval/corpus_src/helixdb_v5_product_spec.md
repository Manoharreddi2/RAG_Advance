---
output: helixdb_v5_product_spec.md
title: HelixDB 5.0 Product Specification
category: Engineering
author: Sarah Lindqvist
date: 2024-07-12
---
# HelixDB 5.0 Product Specification

## Overview

HelixDB 5.0 is the next major release of the Helix distributed SQL database. The release focuses on vector search, lower write latency and simpler operations. General availability is planned for November 2024.

## Goals

- Native vector search inside SQL queries, so customers do not need a separate vector database.
- Reduce p99 write latency by 40% compared with HelixDB 4.2.
- Zero-downtime major version upgrades.
- Support for clusters of up to 512 nodes, up from 256 nodes in version 4.

## Vector Search

HelixDB 5.0 adds a VECTOR column type with up to 4,096 dimensions. Approximate nearest neighbour search uses an HNSW index created with the statement CREATE VECTOR INDEX. Supported distance functions are cosine, dot product and Euclidean (L2).

Hybrid queries can combine vector similarity with normal WHERE filters. The query planner chooses between pre-filtering and post-filtering based on the estimated selectivity of the filter.

## Storage Engine

The new storage engine, code-named Glacier, uses a log-structured merge tree with tiered compaction. Data is compressed with Zstandard by default. Internal benchmarks show a 2.3 times improvement in compression ratio compared with the previous engine.

## Replication and Consistency

Each data range is replicated three times by default using the Raft consensus protocol. Customers can choose between strong consistency and bounded staleness reads with a maximum staleness of 10 seconds.

## Upgrades

Rolling upgrades from HelixDB 4.2 to 5.0 are supported without downtime. Upgrades from versions older than 4.2 must first be upgraded to 4.2.

## Compatibility

HelixDB 5.0 is wire-compatible with the PostgreSQL protocol version 3. Drivers for Java, Python, Go and Node.js are provided. The minimum supported Kubernetes version for the HelixDB operator is 1.27.

## Deprecations

The legacy REST administration API is deprecated in 5.0 and will be removed in 6.0. Customers should migrate to the gRPC administration API.

## Pricing

HelixDB Cloud pricing for vector storage is 0.25 USD per GB per month, in addition to standard storage pricing.
