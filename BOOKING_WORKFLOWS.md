# Appointment Booking Workflows

## Roles and workflows

Authenticated staff, front-desk, practitioner, administrator, and super-administrator accounts may create an appointment for a patient belonging to their clinic. A patient account may self-book only when its user record contains both `role: patient`, a `patient_id`, and the clinic's `clinic_owner_id`. Patient calendar feeds return only that patient's appointments. Staff accounts may reschedule or cancel clinic appointments; patients may reschedule or cancel only their own.

Each booking selects a patient, catalog service, practitioner, duration, local date, and an available local time. Booked appointments appear in day and week views. Selecting an event permits rescheduling or cancellation. Cancellation retains the appointment as a lifecycle record with `status: cancelled` and releases its slot.

## Availability and conflicts

Administrators configure an IANA clinic timezone and weekly working interval for each practitioner under Settings. The default, until explicitly configured, is Monday through Saturday from 09:00 to 18:00 in `Asia/Singapore`. The server rejects malformed local times, appointments outside the working interval, and overlapping appointments. It persists UTC start and end instants plus the clinic timezone and local display fields.

Conflict prevention does not depend on the browser. Each appointment atomically reserves deterministic five-minute lock records in Firestore; simultaneous requests for any shared interval therefore contend and only one can commit. Rescheduling atomically releases obsolete locks and reserves the new interval.

## Reminders and configuration

Reminder delivery is disabled unless an administrator enables it in clinic scheduling settings. A patient must also select the reminder-consent checkbox on their booking. This implementation records both controls; any notification worker must require both before sending a confirmation or reminder.

To configure self-booking, link the authentication user document to an existing clinic patient with `role`, `patient_id`, and `clinic_owner_id`. Practitioner users are active staff-like users created by the clinic owner. Configure each practitioner's weekly schedule individually in Settings before relying on customized hours.
