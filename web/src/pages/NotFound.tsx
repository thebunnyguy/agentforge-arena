import { Compass } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/States";

export function NotFound() {
  return (
    <EmptyState title="This route is outside the arena">
      <Compass size={22} aria-hidden="true" />
      <p>
        The page, agent, task, run, or evaluation could not be resolved from the
        current local API.
      </p>
      <Link className="btn btn-secondary" to="/">
        Return to overview
      </Link>
    </EmptyState>
  );
}
