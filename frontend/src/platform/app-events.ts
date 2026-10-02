/** Window events that let any page ask the app shell to open shared overlays. */
export const OPEN_SEARCH_EVENT = 'oyuns:open-search'
export const OPEN_ASSISTANT_EVENT = 'oyuns:open-assistant'

export const openGlobalSearch = () => window.dispatchEvent(new Event(OPEN_SEARCH_EVENT))
export const openAssistant = () => window.dispatchEvent(new Event(OPEN_ASSISTANT_EVENT))

/** The API refused a request because this session still owes the tenant's second factor. */
export const TWO_FACTOR_REQUIRED_EVENT = 'oyuns:two-factor-required'
