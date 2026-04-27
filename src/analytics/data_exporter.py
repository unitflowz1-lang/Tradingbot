"""Data export functionality for external analysis tools"""

import csv
import json
import logging
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import xml.etree.ElementTree as ET

from src.models import Position, Order, TradingSignal, MarketData
from src.backtesting.performance_analyzer import PerformanceMetrics, TradeAnalysis


class ExportFormat(Enum):
    """Supported export formats"""
    CSV = "csv"
    JSON = "json"
    EXCEL = "xlsx"
    XML = "xml"
    PARQUET = "parquet"


@dataclass
class ExportResult:
    """Result of data export operation"""
    success: bool
    file_path: Optional[str] = None
    record_count: int = 0
    error_message: Optional[str] = None
    export_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert export result to dictionary"""
        return {
            'success': self.success,
            'file_path': self.file_path,
            'record_count': self.record_count,
            'error_message': self.error_message,
            'export_time': self.export_time.isoformat()
        }


class DataExporter:
    """Comprehensive data export system for external analysis"""
    
    def __init__(self, export_directory: str = "exports"):
        self.export_directory = Path(export_directory)
        self.export_directory.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)
        
        # Export configurations
        self.export_configs = {
            'trades': {
                'filename_prefix': 'trades_export',
                'required_fields': ['symbol', 'entry_time', 'exit_time', 'pnl'],
                'optional_fields': ['direction', 'quantity', 'entry_price', 'exit_price', 'commission']
            },
            'signals': {
                'filename_prefix': 'signals_export',
                'required_fields': ['symbol', 'timestamp', 'signal_type'],
                'optional_fields': ['confidence', 'strength', 'reasoning']
            },
            'positions': {
                'filename_prefix': 'positions_export',
                'required_fields': ['symbol', 'direction', 'quantity', 'entry_price'],
                'optional_fields': ['current_price', 'unrealized_pnl', 'stop_loss', 'take_profit']
            },
            'market_data': {
                'filename_prefix': 'market_data_export',
                'required_fields': ['symbol', 'timestamp', 'open', 'high', 'low', 'close'],
                'optional_fields': ['volume', 'bid', 'ask', 'spread']
            },
            'performance': {
                'filename_prefix': 'performance_export',
                'required_fields': ['total_return', 'total_trades', 'win_rate'],
                'optional_fields': ['sharpe_ratio', 'max_drawdown', 'profit_factor']
            }
        }
    
    def export_trades_data(
        self,
        trades_data: List[Dict[str, Any]],
        format_type: ExportFormat = ExportFormat.CSV,
        filename: Optional[str] = None,
        date_range: Optional[tuple] = None,
        symbols: Optional[List[str]] = None
    ) -> ExportResult:
        """
        Export trades data to specified format
        
        Args:
            trades_data: List of trade dictionaries
            format_type: Export format
            filename: Optional custom filename
            date_range: Optional date range filter (start_date, end_date)
            symbols: Optional symbol filter
            
        Returns:
            ExportResult object
        """
        try:
            # Filter data if needed
            filtered_data = self._filter_trades_data(trades_data, date_range, symbols)
            
            if not filtered_data:
                return ExportResult(
                    success=False,
                    error_message="No data to export after filtering"
                )
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.export_configs['trades']['filename_prefix']}_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            # Export based on format
            if format_type == ExportFormat.CSV:
                self._export_to_csv(filtered_data, filepath)
            elif format_type == ExportFormat.JSON:
                self._export_to_json(filtered_data, filepath)
            elif format_type == ExportFormat.EXCEL:
                self._export_to_excel(filtered_data, filepath, 'Trades')
            elif format_type == ExportFormat.XML:
                self._export_to_xml(filtered_data, filepath, 'trades', 'trade')
            elif format_type == ExportFormat.PARQUET:
                self._export_to_parquet(filtered_data, filepath)
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            self.logger.info(f"Exported {len(filtered_data)} trades to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=len(filtered_data)
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export trades data: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    def export_signals_data(
        self,
        signals_data: List[Dict[str, Any]],
        format_type: ExportFormat = ExportFormat.CSV,
        filename: Optional[str] = None,
        date_range: Optional[tuple] = None,
        symbols: Optional[List[str]] = None
    ) -> ExportResult:
        """
        Export signals data to specified format
        
        Args:
            signals_data: List of signal dictionaries
            format_type: Export format
            filename: Optional custom filename
            date_range: Optional date range filter
            symbols: Optional symbol filter
            
        Returns:
            ExportResult object
        """
        try:
            # Filter data if needed
            filtered_data = self._filter_signals_data(signals_data, date_range, symbols)
            
            if not filtered_data:
                return ExportResult(
                    success=False,
                    error_message="No signals data to export after filtering"
                )
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.export_configs['signals']['filename_prefix']}_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            # Export based on format
            if format_type == ExportFormat.CSV:
                self._export_to_csv(filtered_data, filepath)
            elif format_type == ExportFormat.JSON:
                self._export_to_json(filtered_data, filepath)
            elif format_type == ExportFormat.EXCEL:
                self._export_to_excel(filtered_data, filepath, 'Signals')
            elif format_type == ExportFormat.XML:
                self._export_to_xml(filtered_data, filepath, 'signals', 'signal')
            elif format_type == ExportFormat.PARQUET:
                self._export_to_parquet(filtered_data, filepath)
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            self.logger.info(f"Exported {len(filtered_data)} signals to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=len(filtered_data)
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export signals data: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    def export_positions_data(
        self,
        positions: List[Position],
        format_type: ExportFormat = ExportFormat.CSV,
        filename: Optional[str] = None
    ) -> ExportResult:
        """
        Export positions data to specified format
        
        Args:
            positions: List of Position objects
            format_type: Export format
            filename: Optional custom filename
            
        Returns:
            ExportResult object
        """
        try:
            # Convert positions to dictionaries
            positions_data = []
            for position in positions:
                pos_dict = {
                    'position_id': position.position_id,
                    'symbol': position.symbol,
                    'direction': position.direction.value,
                    'quantity': position.quantity,
                    'entry_price': position.entry_price,
                    'current_price': position.current_price,
                    'unrealized_pnl': position.unrealized_pnl,
                    'stop_loss': position.stop_loss,
                    'take_profit': position.take_profit,
                    'opened_at': position.opened_at.isoformat()
                }
                positions_data.append(pos_dict)
            
            if not positions_data:
                return ExportResult(
                    success=False,
                    error_message="No positions data to export"
                )
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.export_configs['positions']['filename_prefix']}_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            # Export based on format
            if format_type == ExportFormat.CSV:
                self._export_to_csv(positions_data, filepath)
            elif format_type == ExportFormat.JSON:
                self._export_to_json(positions_data, filepath)
            elif format_type == ExportFormat.EXCEL:
                self._export_to_excel(positions_data, filepath, 'Positions')
            elif format_type == ExportFormat.XML:
                self._export_to_xml(positions_data, filepath, 'positions', 'position')
            elif format_type == ExportFormat.PARQUET:
                self._export_to_parquet(positions_data, filepath)
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            self.logger.info(f"Exported {len(positions_data)} positions to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=len(positions_data)
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export positions data: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    def export_market_data(
        self,
        market_data: List[MarketData],
        format_type: ExportFormat = ExportFormat.CSV,
        filename: Optional[str] = None,
        date_range: Optional[tuple] = None,
        symbols: Optional[List[str]] = None
    ) -> ExportResult:
        """
        Export market data to specified format
        
        Args:
            market_data: List of MarketData objects
            format_type: Export format
            filename: Optional custom filename
            date_range: Optional date range filter
            symbols: Optional symbol filter
            
        Returns:
            ExportResult object
        """
        try:
            # Convert market data to dictionaries
            market_data_dicts = []
            for data in market_data:
                data_dict = {
                    'symbol': data.symbol,
                    'timestamp': data.timestamp.isoformat(),
                    'open': data.open,
                    'high': data.high,
                    'low': data.low,
                    'close': data.close,
                    'volume': data.volume,
                    'bid': data.bid,
                    'ask': data.ask,
                    'spread': data.spread
                }
                market_data_dicts.append(data_dict)
            
            # Filter data if needed
            filtered_data = self._filter_market_data(market_data_dicts, date_range, symbols)
            
            if not filtered_data:
                return ExportResult(
                    success=False,
                    error_message="No market data to export after filtering"
                )
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.export_configs['market_data']['filename_prefix']}_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            # Export based on format
            if format_type == ExportFormat.CSV:
                self._export_to_csv(filtered_data, filepath)
            elif format_type == ExportFormat.JSON:
                self._export_to_json(filtered_data, filepath)
            elif format_type == ExportFormat.EXCEL:
                self._export_to_excel(filtered_data, filepath, 'MarketData')
            elif format_type == ExportFormat.XML:
                self._export_to_xml(filtered_data, filepath, 'market_data', 'data_point')
            elif format_type == ExportFormat.PARQUET:
                self._export_to_parquet(filtered_data, filepath)
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            self.logger.info(f"Exported {len(filtered_data)} market data points to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=len(filtered_data)
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export market data: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    def export_performance_metrics(
        self,
        metrics: PerformanceMetrics,
        format_type: ExportFormat = ExportFormat.JSON,
        filename: Optional[str] = None
    ) -> ExportResult:
        """
        Export performance metrics to specified format
        
        Args:
            metrics: PerformanceMetrics object
            format_type: Export format
            filename: Optional custom filename
            
        Returns:
            ExportResult object
        """
        try:
            # Convert metrics to dictionary
            metrics_dict = {
                'total_return': metrics.total_return,
                'annualized_return': metrics.annualized_return,
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'win_rate': metrics.win_rate,
                'sharpe_ratio': metrics.sharpe_ratio,
                'sortino_ratio': metrics.sortino_ratio,
                'calmar_ratio': metrics.calmar_ratio,
                'max_drawdown': metrics.max_drawdown,
                'max_drawdown_duration': metrics.max_drawdown_duration,
                'volatility': metrics.volatility,
                'avg_win': metrics.avg_win,
                'avg_loss': metrics.avg_loss,
                'largest_win': metrics.largest_win,
                'largest_loss': metrics.largest_loss,
                'profit_factor': metrics.profit_factor,
                'expectancy': metrics.expectancy,
                'var_95': metrics.var_95,
                'var_99': metrics.var_99,
                'beta': metrics.beta,
                'alpha': metrics.alpha,
                'information_ratio': metrics.information_ratio,
                'avg_trade_duration': metrics.avg_trade_duration,
                'avg_time_in_market': metrics.avg_time_in_market,
                'monthly_returns': metrics.monthly_returns,
                'return_over_max_dd': metrics.return_over_max_dd,
                'sterling_ratio': metrics.sterling_ratio,
                'burke_ratio': metrics.burke_ratio,
                'export_timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{self.export_configs['performance']['filename_prefix']}_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            # Export based on format
            if format_type == ExportFormat.JSON:
                self._export_to_json([metrics_dict], filepath)
            elif format_type == ExportFormat.CSV:
                self._export_to_csv([metrics_dict], filepath)
            elif format_type == ExportFormat.EXCEL:
                self._export_to_excel([metrics_dict], filepath, 'Performance')
            elif format_type == ExportFormat.XML:
                self._export_to_xml([metrics_dict], filepath, 'performance_metrics', 'metric')
            else:
                raise ValueError(f"Unsupported export format: {format_type}")
            
            self.logger.info(f"Exported performance metrics to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=1
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export performance metrics: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    def export_combined_analysis(
        self,
        trades_data: List[Dict[str, Any]],
        signals_data: Optional[List[Dict[str, Any]]] = None,
        positions: Optional[List[Position]] = None,
        metrics: Optional[PerformanceMetrics] = None,
        format_type: ExportFormat = ExportFormat.EXCEL,
        filename: Optional[str] = None
    ) -> ExportResult:
        """
        Export combined analysis data to a single file with multiple sheets/sections
        
        Args:
            trades_data: List of trade dictionaries
            signals_data: Optional list of signal dictionaries
            positions: Optional list of Position objects
            metrics: Optional PerformanceMetrics object
            format_type: Export format
            filename: Optional custom filename
            
        Returns:
            ExportResult object
        """
        try:
            # Generate filename
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"combined_analysis_{timestamp}.{format_type.value}"
            
            filepath = self.export_directory / filename
            
            total_records = 0
            
            if format_type == ExportFormat.EXCEL:
                # Create Excel file with multiple sheets
                with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                    # Trades sheet
                    if trades_data:
                        trades_df = pd.DataFrame(trades_data)
                        trades_df.to_excel(writer, sheet_name='Trades', index=False)
                        total_records += len(trades_data)
                    
                    # Signals sheet
                    if signals_data:
                        signals_df = pd.DataFrame(signals_data)
                        signals_df.to_excel(writer, sheet_name='Signals', index=False)
                        total_records += len(signals_data)
                    
                    # Positions sheet
                    if positions:
                        positions_data = []
                        for pos in positions:
                            positions_data.append({
                                'position_id': pos.position_id,
                                'symbol': pos.symbol,
                                'direction': pos.direction.value,
                                'quantity': pos.quantity,
                                'entry_price': pos.entry_price,
                                'current_price': pos.current_price,
                                'unrealized_pnl': pos.unrealized_pnl,
                                'opened_at': pos.opened_at.isoformat()
                            })
                        positions_df = pd.DataFrame(positions_data)
                        positions_df.to_excel(writer, sheet_name='Positions', index=False)
                        total_records += len(positions_data)
                    
                    # Performance metrics sheet
                    if metrics:
                        metrics_data = [{
                            'metric': 'Total Return',
                            'value': metrics.total_return
                        }, {
                            'metric': 'Annualized Return',
                            'value': metrics.annualized_return
                        }, {
                            'metric': 'Total Trades',
                            'value': metrics.total_trades
                        }, {
                            'metric': 'Win Rate',
                            'value': metrics.win_rate
                        }, {
                            'metric': 'Sharpe Ratio',
                            'value': metrics.sharpe_ratio
                        }, {
                            'metric': 'Max Drawdown',
                            'value': metrics.max_drawdown
                        }, {
                            'metric': 'Profit Factor',
                            'value': metrics.profit_factor
                        }]
                        metrics_df = pd.DataFrame(metrics_data)
                        metrics_df.to_excel(writer, sheet_name='Performance', index=False)
                        total_records += len(metrics_data)
            
            elif format_type == ExportFormat.JSON:
                # Create combined JSON structure
                combined_data = {
                    'export_info': {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'format': 'combined_analysis'
                    },
                    'trades': trades_data if trades_data else [],
                    'signals': signals_data if signals_data else [],
                    'positions': [],
                    'performance_metrics': {}
                }
                
                # Add positions
                if positions:
                    for pos in positions:
                        combined_data['positions'].append({
                            'position_id': pos.position_id,
                            'symbol': pos.symbol,
                            'direction': pos.direction.value,
                            'quantity': pos.quantity,
                            'entry_price': pos.entry_price,
                            'current_price': pos.current_price,
                            'unrealized_pnl': pos.unrealized_pnl,
                            'opened_at': pos.opened_at.isoformat()
                        })
                
                # Add performance metrics
                if metrics:
                    combined_data['performance_metrics'] = {
                        'total_return': metrics.total_return,
                        'annualized_return': metrics.annualized_return,
                        'total_trades': metrics.total_trades,
                        'win_rate': metrics.win_rate,
                        'sharpe_ratio': metrics.sharpe_ratio,
                        'max_drawdown': metrics.max_drawdown,
                        'profit_factor': metrics.profit_factor
                    }
                
                self._export_to_json(combined_data, filepath)
                total_records = len(trades_data or []) + len(signals_data or []) + len(positions or [])
            
            else:
                raise ValueError(f"Combined export not supported for format: {format_type}")
            
            self.logger.info(f"Exported combined analysis with {total_records} records to {filepath}")
            
            return ExportResult(
                success=True,
                file_path=str(filepath),
                record_count=total_records
            )
            
        except Exception as e:
            self.logger.error(f"Failed to export combined analysis: {str(e)}")
            return ExportResult(
                success=False,
                error_message=str(e)
            )
    
    # Helper methods for filtering data
    def _filter_trades_data(
        self,
        trades_data: List[Dict[str, Any]],
        date_range: Optional[tuple],
        symbols: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Filter trades data by date range and symbols"""
        filtered_data = trades_data.copy()
        
        # Filter by date range
        if date_range:
            start_date, end_date = date_range
            filtered_data = []
            for trade in trades_data:
                trade_time = trade.get('entry_time', datetime.now(timezone.utc))
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                
                if start_date <= trade_time <= end_date:
                    filtered_data.append(trade)
        
        # Filter by symbols
        if symbols:
            filtered_data = [
                trade for trade in filtered_data
                if trade.get('symbol') in symbols
            ]
        
        return filtered_data
    
    def _filter_signals_data(
        self,
        signals_data: List[Dict[str, Any]],
        date_range: Optional[tuple],
        symbols: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Filter signals data by date range and symbols"""
        filtered_data = signals_data.copy()
        
        # Filter by date range
        if date_range:
            start_date, end_date = date_range
            filtered_data = []
            for signal in signals_data:
                signal_time = signal.get('timestamp', datetime.now(timezone.utc))
                if isinstance(signal_time, str):
                    signal_time = datetime.fromisoformat(signal_time.replace('Z', '+00:00'))
                
                if start_date <= signal_time <= end_date:
                    filtered_data.append(signal)
        
        # Filter by symbols
        if symbols:
            filtered_data = [
                signal for signal in filtered_data
                if signal.get('symbol') in symbols
            ]
        
        return filtered_data
    
    def _filter_market_data(
        self,
        market_data: List[Dict[str, Any]],
        date_range: Optional[tuple],
        symbols: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Filter market data by date range and symbols"""
        filtered_data = market_data.copy()
        
        # Filter by date range
        if date_range:
            start_date, end_date = date_range
            filtered_data = []
            for data in market_data:
                data_time = data.get('timestamp', datetime.now(timezone.utc))
                if isinstance(data_time, str):
                    data_time = datetime.fromisoformat(data_time.replace('Z', '+00:00'))
                
                if start_date <= data_time <= end_date:
                    filtered_data.append(data)
        
        # Filter by symbols
        if symbols:
            filtered_data = [
                data for data in filtered_data
                if data.get('symbol') in symbols
            ]
        
        return filtered_data
    
    # Helper methods for different export formats
    def _export_to_csv(self, data: Union[List[Dict], Dict], filepath: Path) -> None:
        """Export data to CSV format"""
        if isinstance(data, dict):
            data = [data]
        
        if not data:
            raise ValueError("No data to export")
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = data[0].keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
    
    def _export_to_json(self, data: Union[List[Dict], Dict], filepath: Path) -> None:
        """Export data to JSON format"""
        with open(filepath, 'w', encoding='utf-8') as jsonfile:
            json.dump(data, jsonfile, indent=2, default=str, ensure_ascii=False)
    
    def _export_to_excel(self, data: List[Dict], filepath: Path, sheet_name: str = 'Sheet1') -> None:
        """Export data to Excel format"""
        df = pd.DataFrame(data)
        df.to_excel(filepath, sheet_name=sheet_name, index=False)
    
    def _export_to_xml(self, data: List[Dict], filepath: Path, root_name: str, item_name: str) -> None:
        """Export data to XML format"""
        root = ET.Element(root_name)
        
        for item in data:
            item_element = ET.SubElement(root, item_name)
            for key, value in item.items():
                field_element = ET.SubElement(item_element, key)
                field_element.text = str(value) if value is not None else ''
        
        tree = ET.ElementTree(root)
        tree.write(filepath, encoding='utf-8', xml_declaration=True)
    
    def _export_to_parquet(self, data: List[Dict], filepath: Path) -> None:
        """Export data to Parquet format"""
        df = pd.DataFrame(data)
        df.to_parquet(filepath, index=False)
    
    def get_export_history(self) -> List[Dict[str, Any]]:
        """Get history of export operations"""
        export_files = []
        
        for file_path in self.export_directory.glob('*'):
            if file_path.is_file():
                stat = file_path.stat()
                export_files.append({
                    'filename': file_path.name,
                    'filepath': str(file_path),
                    'size_bytes': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                    'modified_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                })
        
        # Sort by creation time (newest first)
        export_files.sort(key=lambda x: x['created_at'], reverse=True)
        
        return export_files
    
    def cleanup_old_exports(self, days_to_keep: int = 30) -> int:
        """
        Clean up old export files
        
        Args:
            days_to_keep: Number of days to keep files
            
        Returns:
            Number of files deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        deleted_count = 0
        
        for file_path in self.export_directory.glob('*'):
            if file_path.is_file():
                file_time = datetime.fromtimestamp(file_path.stat().st_ctime, tz=timezone.utc)
                if file_time < cutoff_date:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.info(f"Deleted old export file: {file_path.name}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete {file_path.name}: {str(e)}")
        
        return deleted_count