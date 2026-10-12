import { Button, MessageBar, MessageBarBody, MessageBarTitle } from '@fluentui/react-components';
import { Component } from 'react';

/**
 * Keeps a page that fails to draw from taking the whole window with it: the rest (menu, title bar,
 * status bar) stays, and the page says so and can try again. Reset by changing `resetKey`.
 */
export class PageBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(previous) {
    if (this.state.error && previous.resetKey !== this.props.resetKey)
      this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <MessageBar intent="error">
        <MessageBarBody>
          <MessageBarTitle>This page could not be shown.</MessageBarTitle>
          {String(this.state.error?.message ?? this.state.error)}
        </MessageBarBody>
        <Button size="small" onClick={() => this.setState({ error: null })}>
          Try again
        </Button>
      </MessageBar>
    );
  }
}
