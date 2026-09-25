// Cache-busted entry point for the stable model-widget schema.
// The v5 module remains available for existing workflows, while this import
// guarantees that the post-load migration hooks are refreshed after upgrades.
import "./dynamic_model_inputs_v5.js?rev=20260923-google-inputs";
