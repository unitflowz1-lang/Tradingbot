"""
Training Progress Tracking and Visualization

This module provides comprehensive training progress tracking, visualization,
and analysis capabilities for RL training.
"""

import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    PLOTTING_AVAILABLE = True
except ImportError:
    PLOTTING_AVAILABLE = False
from dataclasses import dataclass
from pathlib import Path
import json
from datetime import datetime, timedelta
import logging

from .agent_trainer import TrainingMetrics


@dataclass
class ProgressSnapshot:
    """Snapshot of training progress at a specific point."""
    timestamp: str
    episode: int
    metrics: TrainingMetrics
    
    # Performance indicators
    is_improving: bool
    improvement_rate: float
    stability_score: float
    
    # Convergence indicators
    convergence_score: float
    estimated_episodes_to_convergence: Optional[int]


class PerformanceAnalyzer:
    """Analyzes training performance and provides insights."""
    
    def __init__(self, window_size: int = 100):
        """
        Initialize performance analyzer.
        
        Args:
            window_size: Window size for moving averages
        """
        self.window_size = window_size
        self.logger = logging.getLogger(__name__)
        
    def analyze_convergence(self, metrics_history: List[TrainingMetrics]) -> Dict[str, Any]:
        """
        Analyze training convergence.
        
        Args:
            metrics_history: List of training metrics
            
        Returns:
            Convergence analysis results
        """
        if len(metrics_history) < self.window_size:
            return {'status': 'insufficient_data', 'episodes_analyzed': len(metrics_history)}
            
        rewards = [m.total_reward for m in metrics_history]
        
        # Calculate moving averages
        moving_avg = self._calculate_moving_average(rewards, self.window_size)
        
        # Detect convergence
        convergence_point = self._detect_convergence(moving_avg)
        
        # Calculate convergence metrics
        if convergence_point is not None:
            converged_performance = np.mean(rewards[convergence_point:])
            convergence_stability = np.std(rewards[convergence_point:])
            
            return {
                'status': 'converged',
                'convergence_episode': convergence_point,
                'converged_performance': converged_performance,
                'convergence_stability': convergence_stability,
                'episodes_to_convergence': convergence_point,
                'final_performance': rewards[-1],
                'improvement_from_start': rewards[-1] - rewards[0]
            }
        else:
            # Estimate convergence
            trend = self._calculate_trend(moving_avg[-self.window_size:])
            estimated_episodes = self._estimate_episodes_to_convergence(trend, len(metrics_history))
            
            return {
                'status': 'not_converged',
                'current_trend': trend,
                'estimated_episodes_to_convergence': estimated_episodes,
                'current_performance': rewards[-1],
                'best_performance': max(rewards),
                'improvement_from_start': rewards[-1] - rewards[0]
            }
            
    def analyze_stability(self, metrics_history: List[TrainingMetrics]) -> Dict[str, float]:
        """
        Analyze training stability.
        
        Args:
            metrics_history: List of training metrics
            
        Returns:
            Stability analysis results
        """
        if len(metrics_history) < 2:
            return {'stability_score': 0.0}
            
        rewards = [m.total_reward for m in metrics_history]
        
        # Calculate various stability metrics
        reward_std = np.std(rewards)
        reward_range = max(rewards) - min(rewards)
        
        # Calculate coefficient of variation
        reward_mean = np.mean(rewards)
        cv = reward_std / abs(reward_mean) if reward_mean != 0 else float('inf')
        
        # Calculate trend stability (how consistent is the improvement)
        if len(rewards) >= self.window_size:
            moving_avg = self._calculate_moving_average(rewards, self.window_size // 2)
            trend_changes = sum(1 for i in range(1, len(moving_avg)) 
                              if (moving_avg[i] - moving_avg[i-1]) * (moving_avg[i-1] - moving_avg[i-2]) < 0)
            trend_stability = 1.0 - (trend_changes / len(moving_avg))
        else:
            trend_stability = 0.5
            
        # Overall stability score (0 = unstable, 1 = very stable)
        stability_score = max(0.0, min(1.0, 1.0 - cv / 2.0)) * trend_stability
        
        return {
            'stability_score': stability_score,
            'reward_std': reward_std,
            'reward_range': reward_range,
            'coefficient_of_variation': cv,
            'trend_stability': trend_stability
        }
        
    def analyze_learning_efficiency(self, metrics_history: List[TrainingMetrics]) -> Dict[str, float]:
        """
        Analyze learning efficiency.
        
        Args:
            metrics_history: List of training metrics
            
        Returns:
            Learning efficiency analysis
        """
        if len(metrics_history) < 10:
            return {'efficiency_score': 0.0}
            
        rewards = [m.total_reward for m in metrics_history]
        episodes = list(range(len(rewards)))
        
        # Calculate learning curve slope
        slope = np.polyfit(episodes, rewards, 1)[0]
        
        # Calculate sample efficiency (reward improvement per episode)
        total_improvement = rewards[-1] - rewards[0]
        sample_efficiency = total_improvement / len(rewards) if len(rewards) > 0 else 0
        
        # Calculate plateau detection
        recent_rewards = rewards[-min(50, len(rewards)):]
        plateau_score = 1.0 - (np.std(recent_rewards) / (np.mean(recent_rewards) + 1e-8))
        
        # Overall efficiency score
        efficiency_score = max(0.0, min(1.0, (slope + sample_efficiency) / 2.0))
        
        return {
            'efficiency_score': efficiency_score,
            'learning_slope': slope,
            'sample_efficiency': sample_efficiency,
            'plateau_score': plateau_score,
            'total_improvement': total_improvement
        }
        
    def _calculate_moving_average(self, values: List[float], window: int) -> List[float]:
        """Calculate moving average."""
        if len(values) < window:
            return values
            
        moving_avg = []
        for i in range(window - 1, len(values)):
            avg = np.mean(values[i - window + 1:i + 1])
            moving_avg.append(avg)
            
        return moving_avg
        
    def _detect_convergence(self, moving_avg: List[float], threshold: float = 0.01) -> Optional[int]:
        """Detect convergence point in moving average."""
        if len(moving_avg) < 20:
            return None
            
        # Look for stable period
        for i in range(20, len(moving_avg)):
            recent_values = moving_avg[i-20:i]
            if np.std(recent_values) < threshold:
                return i - 20
                
        return None
        
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend slope."""
        if len(values) < 2:
            return 0.0
            
        x = np.arange(len(values))
        return np.polyfit(x, values, 1)[0]
        
    def _estimate_episodes_to_convergence(self, trend: float, current_episodes: int) -> Optional[int]:
        """Estimate episodes needed for convergence."""
        if abs(trend) < 1e-6:
            return None  # Already converged or no trend
            
        # Simple heuristic: assume convergence when improvement rate drops significantly
        estimated_additional = max(100, int(current_episodes * 0.5))
        return current_episodes + estimated_additional


class ProgressTracker:
    """
    Tracks and visualizes training progress with comprehensive analytics.
    """
    
    def __init__(self, save_dir: str = "training_progress"):
        """
        Initialize progress tracker.
        
        Args:
            save_dir: Directory to save progress data and visualizations
        """
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
        self.metrics_history: List[TrainingMetrics] = []
        self.snapshots: List[ProgressSnapshot] = []
        
        self.analyzer = PerformanceAnalyzer()
        self.logger = logging.getLogger(__name__)
        
        # Visualization settings
        if PLOTTING_AVAILABLE:
            try:
                plt.style.use('seaborn-v0_8')
                sns.set_palette("husl")
            except:
                # Fallback if seaborn style not available
                pass
        
    def add_metrics(self, metrics: TrainingMetrics) -> None:
        """
        Add training metrics to tracker.
        
        Args:
            metrics: Training metrics to add
        """
        self.metrics_history.append(metrics)
        
        # Create progress snapshot
        snapshot = self._create_snapshot(metrics)
        self.snapshots.append(snapshot)
        
        self.logger.debug(f"Added metrics for episode {metrics.episode}")
        
    def _create_snapshot(self, metrics: TrainingMetrics) -> ProgressSnapshot:
        """Create progress snapshot from metrics."""
        # Analyze improvement
        is_improving = False
        improvement_rate = 0.0
        
        if len(self.metrics_history) >= 2:
            recent_rewards = [m.total_reward for m in self.metrics_history[-10:]]
            older_rewards = [m.total_reward for m in self.metrics_history[-20:-10]] if len(self.metrics_history) >= 20 else []
            
            if older_rewards:
                recent_avg = np.mean(recent_rewards)
                older_avg = np.mean(older_rewards)
                is_improving = recent_avg > older_avg
                improvement_rate = (recent_avg - older_avg) / len(recent_rewards)
                
        # Calculate stability
        stability_analysis = self.analyzer.analyze_stability(self.metrics_history)
        stability_score = stability_analysis['stability_score']
        
        # Calculate convergence score
        convergence_analysis = self.analyzer.analyze_convergence(self.metrics_history)
        convergence_score = 1.0 if convergence_analysis['status'] == 'converged' else 0.0
        
        return ProgressSnapshot(
            timestamp=datetime.now().isoformat(),
            episode=metrics.episode,
            metrics=metrics,
            is_improving=is_improving,
            improvement_rate=improvement_rate,
            stability_score=stability_score,
            convergence_score=convergence_score,
            estimated_episodes_to_convergence=convergence_analysis.get('estimated_episodes_to_convergence')
        )
        
    def get_current_status(self) -> Dict[str, Any]:
        """
        Get current training status.
        
        Returns:
            Dictionary with current training status
        """
        if not self.metrics_history:
            return {'status': 'no_data'}
            
        latest_metrics = self.metrics_history[-1]
        latest_snapshot = self.snapshots[-1]
        
        # Get analysis results
        convergence_analysis = self.analyzer.analyze_convergence(self.metrics_history)
        stability_analysis = self.analyzer.analyze_stability(self.metrics_history)
        efficiency_analysis = self.analyzer.analyze_learning_efficiency(self.metrics_history)
        
        return {
            'current_episode': latest_metrics.episode,
            'current_reward': latest_metrics.total_reward,
            'average_reward': latest_metrics.average_reward,
            'is_improving': latest_snapshot.is_improving,
            'improvement_rate': latest_snapshot.improvement_rate,
            'stability_score': stability_analysis['stability_score'],
            'efficiency_score': efficiency_analysis['efficiency_score'],
            'convergence_status': convergence_analysis['status'],
            'estimated_episodes_to_convergence': latest_snapshot.estimated_episodes_to_convergence,
            'total_episodes': len(self.metrics_history),
            'total_training_time': sum(m.episode_time for m in self.metrics_history)
        }
        
    def create_progress_report(self) -> Dict[str, Any]:
        """
        Create comprehensive progress report.
        
        Returns:
            Detailed progress report
        """
        if not self.metrics_history:
            return {'error': 'No training data available'}
            
        # Get all analyses
        convergence_analysis = self.analyzer.analyze_convergence(self.metrics_history)
        stability_analysis = self.analyzer.analyze_stability(self.metrics_history)
        efficiency_analysis = self.analyzer.analyze_learning_efficiency(self.metrics_history)
        
        # Calculate additional statistics
        rewards = [m.total_reward for m in self.metrics_history]
        episode_lengths = [m.episode_length for m in self.metrics_history]
        episode_times = [m.episode_time for m in self.metrics_history]
        
        report = {
            'summary': {
                'total_episodes': len(self.metrics_history),
                'total_training_time': sum(episode_times),
                'average_episode_time': np.mean(episode_times),
                'current_performance': rewards[-1],
                'best_performance': max(rewards),
                'worst_performance': min(rewards),
                'performance_improvement': rewards[-1] - rewards[0]
            },
            'convergence': convergence_analysis,
            'stability': stability_analysis,
            'efficiency': efficiency_analysis,
            'statistics': {
                'reward_mean': np.mean(rewards),
                'reward_std': np.std(rewards),
                'reward_median': np.median(rewards),
                'reward_q25': np.percentile(rewards, 25),
                'reward_q75': np.percentile(rewards, 75),
                'episode_length_mean': np.mean(episode_lengths),
                'episode_length_std': np.std(episode_lengths)
            },
            'recent_performance': {
                'last_10_episodes_mean': np.mean(rewards[-10:]) if len(rewards) >= 10 else np.mean(rewards),
                'last_100_episodes_mean': np.mean(rewards[-100:]) if len(rewards) >= 100 else np.mean(rewards),
                'recent_trend': self.analyzer._calculate_trend(rewards[-50:]) if len(rewards) >= 50 else 0.0
            },
            'generated_at': datetime.now().isoformat()
        }
        
        return report
        
    def plot_training_progress(self, save_path: Optional[str] = None, show: bool = True) -> None:
        """
        Plot comprehensive training progress visualization.
        
        Args:
            save_path: Path to save the plot
            show: Whether to display the plot
        """
        if not PLOTTING_AVAILABLE:
            self.logger.warning("Matplotlib not available. Install with: pip install matplotlib seaborn")
            return
            
        if not self.metrics_history:
            self.logger.warning("No training data to plot")
            return
            
        # Prepare data
        episodes = [m.episode for m in self.metrics_history]
        rewards = [m.total_reward for m in self.metrics_history]
        avg_rewards = [m.average_reward for m in self.metrics_history]
        episode_lengths = [m.episode_length for m in self.metrics_history]
        losses = [m.loss for m in self.metrics_history if m.loss is not None]
        
        # Create subplots
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('Training Progress Dashboard', fontsize=16, fontweight='bold')
        
        # Plot 1: Reward progression
        axes[0, 0].plot(episodes, rewards, alpha=0.6, label='Episode Reward')
        axes[0, 0].plot(episodes, avg_rewards, linewidth=2, label='Average Reward')
        axes[0, 0].set_xlabel('Episode')
        axes[0, 0].set_ylabel('Reward')
        axes[0, 0].set_title('Reward Progression')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)
        
        # Plot 2: Episode length
        axes[0, 1].plot(episodes, episode_lengths, color='orange', alpha=0.7)
        axes[0, 1].set_xlabel('Episode')
        axes[0, 1].set_ylabel('Episode Length')
        axes[0, 1].set_title('Episode Length Over Time')
        axes[0, 1].grid(True, alpha=0.3)
        
        # Plot 3: Loss (if available)
        if losses:
            loss_episodes = [m.episode for m in self.metrics_history if m.loss is not None]
            axes[1, 0].plot(loss_episodes, losses, color='red', alpha=0.7)
            axes[1, 0].set_xlabel('Episode')
            axes[1, 0].set_ylabel('Loss')
            axes[1, 0].set_title('Training Loss')
            axes[1, 0].grid(True, alpha=0.3)
        else:
            axes[1, 0].text(0.5, 0.5, 'No Loss Data Available', 
                           ha='center', va='center', transform=axes[1, 0].transAxes)
            axes[1, 0].set_title('Training Loss')
            
        # Plot 4: Performance distribution
        axes[1, 1].hist(rewards, bins=30, alpha=0.7, color='green', edgecolor='black')
        axes[1, 1].axvline(np.mean(rewards), color='red', linestyle='--', label=f'Mean: {np.mean(rewards):.2f}')
        axes[1, 1].axvline(np.median(rewards), color='blue', linestyle='--', label=f'Median: {np.median(rewards):.2f}')
        axes[1, 1].set_xlabel('Reward')
        axes[1, 1].set_ylabel('Frequency')
        axes[1, 1].set_title('Reward Distribution')
        axes[1, 1].legend()
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"Saved training progress plot to {save_path}")
            
        if show:
            plt.show()
        else:
            plt.close()
            
    def plot_performance_analysis(self, save_path: Optional[str] = None, show: bool = True) -> None:
        """
        Plot detailed performance analysis.
        
        Args:
            save_path: Path to save the plot
            show: Whether to display the plot
        """
        if not PLOTTING_AVAILABLE:
            self.logger.warning("Matplotlib not available. Install with: pip install matplotlib seaborn")
            return
            
        if len(self.metrics_history) < 10:
            self.logger.warning("Insufficient data for performance analysis")
            return
            
        rewards = [m.total_reward for m in self.metrics_history]
        episodes = list(range(len(rewards)))
        
        # Calculate moving averages
        window_sizes = [10, 50, 100]
        moving_averages = {}
        
        for window in window_sizes:
            if len(rewards) >= window:
                moving_averages[window] = self.analyzer._calculate_moving_average(rewards, window)
                
        # Create plot
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        fig.suptitle('Performance Analysis', fontsize=16, fontweight='bold')
        
        # Plot 1: Reward with moving averages
        axes[0].plot(episodes, rewards, alpha=0.3, color='gray', label='Raw Rewards')
        
        colors = ['blue', 'red', 'green']
        for i, (window, ma) in enumerate(moving_averages.items()):
            ma_episodes = episodes[window-1:window-1+len(ma)]
            axes[0].plot(ma_episodes, ma, color=colors[i], linewidth=2, 
                        label=f'MA-{window}')
                        
        axes[0].set_xlabel('Episode')
        axes[0].set_ylabel('Reward')
        axes[0].set_title('Reward Trends with Moving Averages')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Plot 2: Performance metrics over time
        stability_scores = [s.stability_score for s in self.snapshots]
        improvement_rates = [s.improvement_rate for s in self.snapshots]
        
        ax2_twin = axes[1].twinx()
        
        line1 = axes[1].plot(episodes, stability_scores, color='blue', label='Stability Score')
        line2 = ax2_twin.plot(episodes, improvement_rates, color='red', label='Improvement Rate')
        
        axes[1].set_xlabel('Episode')
        axes[1].set_ylabel('Stability Score', color='blue')
        ax2_twin.set_ylabel('Improvement Rate', color='red')
        axes[1].set_title('Training Stability and Improvement Rate')
        
        # Combine legends
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        axes[1].legend(lines, labels, loc='upper left')
        
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            self.logger.info(f"Saved performance analysis plot to {save_path}")
            
        if show:
            plt.show()
        else:
            plt.close()
            
    def save_progress_data(self, filepath: str) -> None:
        """
        Save progress tracking data to file.
        
        Args:
            filepath: Path to save data
        """
        data = {
            'metrics_history': [
                {
                    'episode': m.episode,
                    'total_reward': m.total_reward,
                    'episode_length': m.episode_length,
                    'average_reward': m.average_reward,
                    'loss': m.loss,
                    'episode_time': m.episode_time,
                    'total_time': m.total_time,
                    'custom_metrics': m.custom_metrics
                }
                for m in self.metrics_history
            ],
            'progress_report': self.create_progress_report(),
            'saved_at': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
            
        self.logger.info(f"Saved progress data to {filepath}")
        
    def load_progress_data(self, filepath: str) -> None:
        """
        Load progress tracking data from file.
        
        Args:
            filepath: Path to load data from
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        # Reconstruct metrics history
        self.metrics_history = []
        for m_data in data['metrics_history']:
            metrics = TrainingMetrics(
                episode=m_data['episode'],
                total_reward=m_data['total_reward'],
                episode_length=m_data['episode_length'],
                average_reward=m_data['average_reward'],
                loss=m_data.get('loss'),
                episode_time=m_data.get('episode_time', 0.0),
                total_time=m_data.get('total_time', 0.0),
                custom_metrics=m_data.get('custom_metrics', {})
            )
            self.metrics_history.append(metrics)
            
        # Recreate snapshots
        self.snapshots = []
        for metrics in self.metrics_history:
            snapshot = self._create_snapshot(metrics)
            self.snapshots.append(snapshot)
            
        self.logger.info(f"Loaded progress data from {filepath}")
        
    def export_to_csv(self, filepath: str) -> None:
        """
        Export training data to CSV format.
        
        Args:
            filepath: Path to save CSV file
        """
        if not PANDAS_AVAILABLE:
            self.logger.warning("Pandas not available. Install with: pip install pandas")
            return
            
        if not self.metrics_history:
            self.logger.warning("No data to export")
            return
            
        # Prepare data for DataFrame
        data = []
        for i, metrics in enumerate(self.metrics_history):
            row = {
                'episode': metrics.episode,
                'total_reward': metrics.total_reward,
                'episode_length': metrics.episode_length,
                'average_reward': metrics.average_reward,
                'loss': metrics.loss,
                'episode_time': metrics.episode_time,
                'total_time': metrics.total_time,
                'stability_score': self.snapshots[i].stability_score if i < len(self.snapshots) else None,
                'improvement_rate': self.snapshots[i].improvement_rate if i < len(self.snapshots) else None,
                'is_improving': self.snapshots[i].is_improving if i < len(self.snapshots) else None
            }
            
            # Add custom metrics
            for key, value in metrics.custom_metrics.items():
                row[f'custom_{key}'] = value
                
            data.append(row)
            
        # Create DataFrame and save
        df = pd.DataFrame(data)
        df.to_csv(filepath, index=False)
        
        self.logger.info(f"Exported training data to {filepath}")