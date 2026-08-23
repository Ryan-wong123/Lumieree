# Calendar Booking Workflows

## Scope

The first booking phase permits authenticated staff, administrators, and super administrators to view appointment calendars, search availability, create appointments, reschedule appointments, and cancel appointments. Patient self-booking, recurring appointments, waitlists, resource booking, reminders, and external calendar synchronization are future work and are not available.

## Calendar and availability

The Appointments page provides day and week views. Both views display appointments between 10:00 and 21:00, with one-hour scheduling slots. Selecting a calendar date opens that date's appointment list. The availability action reads persisted appointments for the selected tenant and reports unoccupied hours. Availability shown in the browser is advisory: the server repeats conflict detection immediately before every create or reschedule write.

## Appointment actions

To create an appointment, an authorized user selects a date and available hour and supplies a patient name and appointment reason; contact information is optional. To reschedule, the user expands the appointment action, selects a destination date and hour, and saves. If that slot became unavailable, no change is made and the page displays an explanatory message. Cancellation requires confirmation and removes only the selected appointment slot.

All identifiers, ISO dates, hours, and required text inputs are validated on the server. Appointment documents are checked for tenant ownership before modification. Existing documents using the original `date`, `patient_name`, `contact`, and `slots` fields remain supported; no migration is required. New appointments use the same fields and store one occupied hour in `slots`.

## Permissions and conflict handling

Appointment endpoints require an authenticated session with the existing `staff`, `admin`, or `super_admin` role. Reads and writes are restricted by `owner_id`. A time is unavailable when any owned appointment document for that date has a non-empty value at the requested hour. Conflict detection is centralized in `occupied_appointment_hours` and is shared by availability, create, and reschedule paths.
