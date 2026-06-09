//! Governed desktop-control support.
//!
//! Phase 1 keeps this module read-only: it reports local permission readiness
//! and feeds the visible safety strip. Pointer and keyboard actuation remain
//! hard-locked elsewhere until command governance ships.

pub mod actuation_lease;
pub mod denial_codes;
pub mod keyboard_bounds;
pub mod permissions;
pub mod policy;
pub mod stop_state;

pub use permissions::{current_permission_readiness, DesktopPermissionReadiness};
pub use policy::{
    evaluate_native_control_command_policy, evaluate_observation_policy, DesktopControlMode,
    NativeControlCapability, NativeControlCommandPolicy, ObservationCapability,
};
