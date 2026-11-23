---
output: information_security_policy_2024.docx
title: Information Security Policy v4
category: Security
author: Marcus Chen
date: 2024-05-20
---
# Information Security Policy v4

## 1. Introduction

This Information Security Policy (version 4) sets the minimum security requirements for all Helix Systems Inc. employees, contractors and systems. It was approved by the Chief Information Security Officer on May 20, 2024 and replaces version 3. The update aligns the policy with the ISO/IEC 27001:2022 standard, which the company plans to be certified against by the end of 2025.

## 2. Data Classification

All company information must be classified into one of four levels: Public, Internal, Confidential and Restricted. Restricted is a new level for data whose disclosure would cause severe harm, such as encryption keys, authentication secrets and unreleased merger information. Restricted data may only be stored in the approved secrets vault.

Confidential information includes customer data, source code, unpublished financial results and employee personal data. Confidential and Restricted information must be encrypted at rest and in transit.

## 3. Passwords and Authentication

Passwords must be at least 14 characters long. Passphrases made of several random words are encouraged. Periodic password changes are no longer required; passwords must be changed only when there is evidence or suspicion of compromise.

Multi-factor authentication (MFA) is required for all company systems. SMS codes are no longer accepted as a second factor; employees must use the authenticator app or a hardware security key.

User accounts are locked after 10 consecutive failed login attempts.

<!-- pagebreak -->

## 4. Devices

Company laptops must use full-disk encryption and must lock the screen automatically after 5 minutes of inactivity. Personal devices may be used to read company email only if they are enrolled in the mobile device management system and run a supported operating system version.

Lost or stolen devices must be reported to the IT service desk within 4 hours so that the device can be wiped remotely.

## 5. Access Management

Access to systems is granted on a least-privilege basis and must be approved by the system owner. Access rights to Confidential systems are reviewed every quarter; other access rights are reviewed twice a year. When an employee leaves the company, all access must be revoked on their last working day.

## 6. Security Training

All employees must complete security awareness training within 30 days of joining and then once every year. Engineers must also complete secure coding training every year. Phishing simulations are carried out every month.

## 7. Incident Reporting

Suspected security incidents must be reported to security@helixsystems.example or through the #security-incidents channel within 1 hour of discovery. The incident response process is described in the Incident Response Runbook.

## 8. Exceptions

Exceptions to this policy must be requested through the risk register and approved by the CISO. Approved exceptions expire after 6 months and must then be renewed or closed.
