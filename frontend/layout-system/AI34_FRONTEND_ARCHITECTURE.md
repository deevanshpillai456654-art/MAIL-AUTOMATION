# AI34 Frontend Architecture

The AI34 frontend uses progressive enhancement:
1. Existing backend-compatible HTML and `enterprise-ui.js` remain the source of business behavior.
2. `enterprise-ui.css` supplies the expanded design-token system and premium components.
3. `premium-ui.js` adds non-critical UI enhancements: theme switching, assistant panel, onboarding progress, and dashboard hero.
4. Extension popup/options UI now share `extensions/*/ui.css` to reduce duplication.

This preserves OAuth/account onboarding behavior while upgrading visual quality and maintainability.
