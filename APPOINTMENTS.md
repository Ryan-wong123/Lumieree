# Appointment Workflow Report

## Scope

The appointment module provides authenticated, tenant-scoped scheduling for the existing hourly calendar model. It supports day and week calendar views, availability lookup, creation through the schedule table, and rescheduling or cancellation of an occupied slot.

## Operation

Authorized users open **Appointment**, choose the day or week view, and select a calendar date. Availability search reports open whole-hour starts from 10:00 through 20:00. A booking is created by entering the patient details and a description in an available time cell, then saving the schedule. An occupied cell exposes actions for moving that appointment to a validated date and hour or cancelling it.

All dates, hours, appointment identifiers, ownership, and occupied slots are validated on the server. The server reloads persisted scheduling data immediately before create or reschedule operations. If another booking occupies the requested time, no conflicting change is saved and the user receives a clear message that the time is no longer available.

## Permissions and data compatibility

Every appointment endpoint requires an authenticated session. Queries and mutations use the existing `owner_id` tenant boundary, and identifier-based actions additionally verify document ownership. No migration is required: documents retain `patient_name`, `contact`, `date`, `slots`, `timestamp`, and `owner_id`. Each non-empty hourly `slots` entry represents an occupied appointment time.

## Deferred work

Self-service booking, recurring appointments, waitlists, resource booking, reminders, variable-duration scheduling, practitioner calendars, and external calendar synchronization are not provided in this phase.
