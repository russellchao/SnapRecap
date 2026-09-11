import "./About.css";

export default function About() {
  return (
    <div className="about">
      <header className="about-hero">
        <p className="about-wordmark">Snap Recap</p>
        <h1 className="about-headline">
          <span>The box score tells you what happened.</span>
          <span>This explains why.</span>
        </h1>
        <p className="about-sub">
          Snap Recap reads every play of a finished NFL game — win-probability swings,
          efficiency by situation, the plays that decided it, what changed after an
          injury — and turns the parts that mattered into plain sentences. No highlight
          reel, no play-by-play transcript. Just the explanation.
        </p>
      </header>

      <hr className="about-rule" />

      <section className="about-pipeline">
        <h2>How a recap gets made</h2>
        <ol className="pipeline-list">
          <li>
            <span className="pipeline-num">1</span>
            <div>
              <h3>Every play gets measured</h3>
              <p>
                Not just what happened on the field, but how much it actually changed
                the game — how far the odds swung on that one snap.
              </p>
            </div>
          </li>
          <li>
            <span className="pipeline-num">2</span>
            <div>
              <h3>The numbers find what mattered</h3>
              <p>
                Turnovers, explosive plays, red-zone execution, and more — every point
                of the final margin gets sorted into one of these buckets, so you can
                see which ones actually moved the needle. The same measurements pick out
                the winner's best plays, the losing team's costliest ones, and the
                moments an injury changed how a team moved the ball.
              </p>
            </div>
          </li>
          <li>
            <span className="pipeline-num">3</span>
            <div>
              <h3>Then it's put into plain words</h3>
              <p>
                Those plays and numbers become short write-ups you can actually read —
                how the winner won it, where the loser lost it, what the injuries cost —
                and any question you ask gets answered from that same information. The
                write-up never decides on its own what counts as important.
              </p>
            </div>
          </li>
        </ol>
      </section>

      <hr className="about-rule" />

      <section className="about-split">
        <div className="split-col split-col--home">
          <h2>What the analysis decides</h2>
          <ul>
            <li>Which plays defined the game</li>
            <li>How the final margin breaks down by category</li>
            <li>Which team signals were unusual enough to matter</li>
            <li>Whether an injury changed how a team moved the ball</li>
            <li>How much confidence a small-sample number deserves</li>
          </ul>
        </div>
        <div className="split-divider" aria-hidden="true" />
        <div className="split-col split-col--away">
          <h2>What the writing layer does</h2>
          <ul>
            <li>Turns selected plays and numbers into sentences</li>
            <li>Describes how big a swing was, without guessing at why it happened</li>
            <li>Answers questions about a game, grounded in what's already decided</li>
            <li>Never re-ranks or re-selects what counts as important</li>
          </ul>
        </div>
      </section>

      <hr className="about-rule" />

      <footer className="about-footer">
        <p>Built for fans who want the real explanation, not just the highlight reel.</p>
        <p className="about-credit">
          Data from nflfastR. Analysis in Python. Language by Claude.
        </p>
      </footer>
    </div>
  );
}