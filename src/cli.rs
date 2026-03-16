use crate::logging::LoggingSettings;
use clap::Parser;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[clap(
    name = "Jellycleanerr",
    version = "1.0.0",
    about = "Jellycleanerr is a CLI tool for cleaning up watched and idle Jellyfin media."
)]
pub struct Cli {
    /// Perform actual deletion of files. If not set the program will operate in
    /// a "dry run" mode
    #[clap(short = 'd', long)]
    pub force_delete: bool,
    /// You can either provide a single log level (like `info`) or use a more
    /// detailed syntax like `off,jellycleanerr=debug,reqwest=info` (similar to
    /// `tracing_subscriber::filter::EnvFilter` syntax)
    #[clap(short, long, env = "LOG_LEVEL")]
    pub log_level: LoggingSettings,
    /// Path to the config file
    #[clap(short, long)]
    pub config: PathBuf,
}
